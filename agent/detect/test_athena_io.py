"""Athena 연결 시험. 가짜 boto3 클라이언트로 쿼리 보내기·기다리기·결과 변환·INSERT 만들기를 본다 (진짜 Athena에서는 아직 안 돌려 봤다).

실행: python3 test_athena_io.py
"""
from datetime import datetime

import athena_io
from athena_io import AthenaError, AthenaIO
from run_job import main as run_main

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


class FakeAthena:
    """boto3 athena 클라이언트 흉내. states는 get_query_execution이 차례로 돌려줄 상태, pages는 결과 페이지."""

    def __init__(self, states=("SUCCEEDED",), pages=None, reason="boom"):
        self.states, self.pages, self.reason = list(states), pages or [], reason
        self.sent, self.polls, self.stopped = [], 0, 0

    def start_query_execution(self, QueryString, WorkGroup, QueryExecutionContext):
        self.sent.append({"sql": QueryString, "wg": WorkGroup, "ctx": QueryExecutionContext})
        return {"QueryExecutionId": f"q{len(self.sent)}"}

    def get_query_execution(self, QueryExecutionId):
        self.polls += 1
        st = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"QueryExecution": {"Status": {"State": st, "StateChangeReason": self.reason}}}

    def get_query_results(self, QueryExecutionId, NextToken=None):
        i = int(NextToken or 0)
        page = {"ResultSet": self.pages[i]}
        if i + 1 < len(self.pages):
            page["NextToken"] = str(i + 1)
        return page

    def stop_query_execution(self, QueryExecutionId):
        self.stopped += 1


def meta(*cols):
    return {"ResultSetMetadata": {"ColumnInfo": [{"Name": n, "Type": t} for n, t in cols]}}


def row(*vals):
    return {"Data": [({"VarCharValue": v} if v is not None else {}) for v in vals]}


COLS = (("pg", "varchar"), ("attempts", "bigint"), ("rate", "double"), ("ok", "boolean"), ("seen", "timestamp"))
no_sleep = lambda s: None

# --- 읽기 ---
fake = FakeAthena(states=("QUEUED", "RUNNING", "SUCCEEDED"), pages=[
    {**meta(*COLS), "Rows": [row("pg", "attempts", "rate", "ok", "seen"), row("PG_A", "40", "0.75", "true", "2026-10-20 15:10:00.000")]},
    {**meta(*COLS), "Rows": [row("PG_B", "7", None, "false", None)]}])
io = AthenaIO("wg-detect", "gold_b", client=fake, sleep=no_sleep)
out = io.query("SELECT 1")
check("쿼리가 workgroup과 데이터베이스를 지정해 나감", (fake.sent[0]["wg"], fake.sent[0]["ctx"]), ("wg-detect", {"Database": "gold_b"}))
check("끝날 때까지 상태를 확인함(대기 → 실행 → 성공)", fake.polls, 3)
check("컬럼 타입대로 변환(정수, 실수, 불리언, 문자열)", (out[0]["attempts"], out[0]["rate"], out[0]["ok"], out[0]["pg"]), (40, 0.75, True, "PG_A"))
check("두 번째 페이지도 읽고, 첫 줄(컬럼 이름)은 건너뜀, 빈 값은 None", (len(out), out[1]["rate"], out[1]["seen"]), (2, None, None))
check("시각은 문자열 그대로 돌려줌", out[0]["seen"], "2026-10-20 15:10:00.000")

# --- 실패, 시간 초과 ---
try:
    AthenaIO("w", client=FakeAthena(states=("FAILED",), reason="SYNTAX_ERROR"), sleep=no_sleep).query("x")
    check("실패한 쿼리는 오류", "통과됨", "오류")
except AthenaError as e:
    check("실패한 쿼리는 오류, 이유가 메시지에 들어감", "SYNTAX_ERROR" in str(e), True)
clock = iter(range(0, 1000, 50))
slow = FakeAthena(states=("RUNNING",))
try:
    AthenaIO("w", client=slow, sleep=no_sleep, now=lambda: next(clock)).query("x")
    check("시간 초과는 오류", "통과됨", "오류")
except AthenaError:
    check("시간 초과는 오류이고 쿼리를 멈추려고 시도함", slow.stopped, 1)

# --- 쓰기 ---
runs = [{"run_id": "20261020T1510Z", "kind": "REGULAR", "request_id": None, "judged_from": "2026-10-20 15:05:00",
         "judged_to": "2026-10-20 15:10:00", "started_at": "2026-10-20 15:10:07", "anomaly_count": 2}]
fake = FakeAthena()
AthenaIO("w", client=fake, sleep=no_sleep).write("detection_runs", runs)
sql = fake.sent[0]["sql"]
check("INSERT 문: 표, 시각 타입, NULL, 숫자, 파티션(dt, hour)", ("INSERT INTO gold_b.detection_runs" in sql, "TIMESTAMP '2026-10-20 15:10:07'" in sql, "NULL" in sql, ", 2, '2026-10-20', '15')" in sql), (True, True, True, True))
fake = FakeAthena()
AthenaIO("w", client=fake, sleep=no_sleep).write("reprocess_events", [{"request_id": "rq'1", "step": "VERIFIED", "at": datetime(2026, 10, 20, 16, 30), "detail": "it's \"x\""}])
check("작은따옴표는 두 번 써서 막음", "'rq''1'" in fake.sent[0]["sql"] and "'it''s \"x\"'" in fake.sent[0]["sql"], True)
fake = FakeAthena()
AthenaIO("w", client=fake, sleep=no_sleep).write("detection_runs", [])
check("쓸 줄이 없으면 아무것도 안 보냄", fake.sent, [])
for bad, why in ((("users", runs), "허용 목록 밖 표"), (("detection_runs", [{"run_id": "a", "drop": 1, "started_at": "2026-10-20 15:10:07"}]), "없는 컬럼"),
                 (("detection_runs", [{"run_id": "a"}]), "파티션 기준 컬럼이 빔"), (("detection_runs", [{"started_at": "2026-10-20 15:10:07", "anomaly_count": "2"}]), "숫자 컬럼에 문자열")):
    try:
        AthenaIO("w", client=FakeAthena(), sleep=no_sleep).write(*bad)
        check(f"쓰기 거절: {why}", "통과됨", "오류")
    except ValueError:
        check(f"쓰기 거절: {why}", "오류", "오류")
many = [dict(runs[0], run_id=f"r{i}", started_at="2026-10-20 15:10:07") for i in range(3000)]
fake = FakeAthena()
AthenaIO("w", client=fake, sleep=no_sleep).write("detection_runs", many)
check("줄이 많으면 크기 한도 안에서 여러 번에 나눠 보냄", (len(fake.sent) > 1, all(len(s["sql"]) <= athena_io.MAX_QUERY_BYTES for s in fake.sent), sum(s["sql"].count("'r") for s in fake.sent)), (True, True, 3000))
check("표 3개가 모두 파티션 기준 시각 컬럼을 가짐", all(sp["partition_by"] in sp["columns"] for sp in athena_io.TABLE_SPECS.values()), True)

# --- 실행 진입점 ---
class Rec:
    def __init__(self):
        self.q, self.w = [], []

    def query(self, sql):
        self.q.append(sql)
        return []

    def write(self, table, rows):
        self.w.append((table, len(rows)))


rec = Rec()
s = run_main(env={}, io=rec, now=datetime(2026, 10, 20, 15, 12, 41))
check("진입점: 순찰 한 바퀴가 돌고 순찰 기록을 씀", (s["regular"]["run_id"], ("detection_runs", 1) in rec.w), ("20261020T1510Z", True))
check("진입점: Athena용 시각 표기(TIMESTAMP '...')로 쿼리를 보냄", any("TIMESTAMP '" in q for q in rec.q), True)
rec2 = Rec()
s = run_main(env={"JUDGE_TICK": "2026-10-20T15:10:00Z"}, io=rec2, now=datetime(2026, 10, 20, 15, 31, 2))
check("진입점: JUDGE_TICK을 주면 늦게 재시도해도 그 시각의 순찰 번호를 씀(이중 저장 방지)", s["regular"]["run_id"], "20261020T1510Z")
try:
    run_main(env={})
    check("진입점: workgroup이 없으면 종료", "통과됨", "종료")
except SystemExit:
    check("진입점: workgroup이 없으면 종료", "종료", "종료")
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
