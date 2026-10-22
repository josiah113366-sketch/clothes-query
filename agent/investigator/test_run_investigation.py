"""조사 실행 진입점 시험. 가짜 Athena(조회 결과와 쓰기 기록)와 가짜 모델로 한 바퀴를 돌린다.

실행: python3 test_run_investigation.py
"""
import json
from datetime import datetime

from run_investigation import find_pending, main, mark_expired, run_one

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


NOW = datetime(2026, 10, 21, 10, 0, 0)
W = {"window_start": "2026-10-21T09:00:00", "window_end": "2026-10-21T09:30:00"}


def anomaly(aid, **kw):
    return {"anomaly_id": aid, "rule_id": "R1_PG_FAILURES", "anomaly_type": "PG_FAILURE_SPIKE", "scope_type": "pg", "scope_key": "PG_A",
            "status": "OPEN", "detected_at": "2026-10-21 09:40:00", **kw}


class FakeIO:
    """query는 SQL에 든 표 이름으로 정해 둔 줄을 돌려주고, write는 기록해 둔다."""

    def __init__(self, anomalies, runs=()):
        self.anomalies, self.runs, self.written, self.sql = list(anomalies), list(runs), [], []

    def query(self, sql):
        self.sql.append(sql)
        if "FROM gold_b.anomaly_current" in sql:
            return self.anomalies
        if "FROM agent.investigation_runs" in sql:
            return self.runs
        if "payment_attempts" in sql:
            return [{"pg": "PG_A", "attempts": 40, "pg_cause_failures": 30}]
        return []

    def write(self, table, rows):
        self.written.append((table, rows))


class FakeModel:
    """정해 둔 순서대로 응답하는 가짜 모델. BedrockConverse처럼 model_id와 usage를 가진다."""
    model_id = "fake-model"

    def __init__(self, *turns):
        self.turns, self.usage = list(turns), {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def __call__(self, system, messages, tool_specs):
        self.usage["calls"] += 1
        return {"role": "assistant", "content": self.turns.pop(0)}


def use(i, name, **args):
    return {"toolUse": {"toolUseId": f"t{i}", "name": name, "input": args}}


REPORT = dict(cause_layer="PAYMENT", conclusion="PG_A 장애입니다.", claims=[{"text": "PG_A 실패 30건", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]}])
GOOD = [[use(1, "payment_summary", **W)], [use(2, "submit_report", **REPORT)]]

# --- 조사할 이상 고르기 ---
io = FakeIO([anomaly("a-1"), anomaly("a-2"), anomaly("a-3"), anomaly("a-4"), anomaly("a-5")],
            runs=[{"anomaly_id": "a-2", "status": "REPORTED"}, {"anomaly_id": "a-3", "status": "ERROR"}, {"anomaly_id": "a-4", "status": "ERROR"},
                  {"anomaly_id": "a-4", "status": "ERROR"}, {"anomaly_id": "a-4", "status": "ERROR"}])
got = [a["anomaly_id"] for a in find_pending(io.query, NOW, limit=10)]
check("이미 조사한 이상(a-2)은 빼고, 오류 1번(a-3)은 다시, 오류 3번(a-4)은 포기, 나머지는 포함", got, ["a-1", "a-3", "a-5"])
check("한 번에 조사할 개수에 상한을 둠", [a["anomaly_id"] for a in find_pending(io.query, NOW, limit=2)], ["a-1", "a-3"])
q_an = [x for x in io.sql if "FROM gold_b.anomaly_current" in x][0]
check("최근 이상(24시간)만, 상태 OPEN만 읽음 (해소 줄 제외)", ("status = 'OPEN'" in q_an, "TIMESTAMP '2026-10-20 10:00:00'" in q_an), (True, True))
check("오래된 이상부터 읽고, 이미 조사한 이상(a-2)과 오류 한도를 넘긴 이상(a-4)은 쿼리에서 빼서 앞을 채우지 않게 함",
      ("ORDER BY detected_at LIMIT" in q_an, "NOT IN ('a-2', 'a-4')" in q_an), (True, True))
io2 = FakeIO([anomaly("b-1")], runs=[])
find_pending(io2.query, NOW, limit=3)
check("조사 기록이 없으면 NOT IN 조건을 붙이지 않음", "NOT IN" in [x for x in io2.sql if "anomaly_current" in x][0], False)
io3 = FakeIO([anomaly("c-1", anomaly_id="c-1")], runs=[{"anomaly_id": "x' OR '1'='1", "status": "REPORTED"}])
find_pending(io3.query, NOW, limit=3)
check("이상 id에 따옴표가 있으면 쿼리에 넣지 않음(쿼리 주입 방지)", "OR '1'='1" in [x for x in io3.sql if "anomaly_current" in x][0], False)
io4 = FakeIO([anomaly("e-1")], runs=[{"anomaly_id": "e-1", "status": "EXPIRED"}])
check("EXPIRED로 표시된 이상은 조사한 것이 아니므로 조사 기간을 늘려 다시 돌리면 조사 대상이 됨", [a["anomaly_id"] for a in find_pending(io4.query, NOW, limit=3, lookback_hours=72)], ["e-1"])

# --- 조사 기간을 넘긴 이상 표시(EXPIRED) ---
old_io = FakeIO([anomaly("o-1", detected_at="2026-10-19 09:00:00"), anomaly("o-2", detected_at="2026-10-19 10:00:00")], runs=[{"anomaly_id": "o-2", "status": "ERROR"}])
n = mark_expired(old_io.query, old_io.write, NOW, 24)
tbl, rows = old_io.written[0]
check("기간 넘긴 미조사 이상에 EXPIRED 줄을 씀(조사 기록이 이미 있는 o-2는 제외)", (n, tbl, [(r["anomaly_id"], r["status"]) for r in rows]), (1, "investigation_runs", [("o-1", "EXPIRED")]))
check("EXPIRED 줄에 이유가 남음", "24시간" in rows[0]["error"], True)
q_old = [x for x in old_io.sql if "anomaly_current" in x][0]
check("EXPIRED 대상은 조사 기간(24시간) 밖 ~ 7일 안의 OPEN 이상", ("detected_at < TIMESTAMP '2026-10-20 10:00:00'" in q_old, "detected_at >= TIMESTAMP '2026-10-13 10:00:00'" in q_old), (True, True))
none_io = FakeIO([], runs=[])
check("표시할 이상이 없으면 아무것도 쓰지 않음", (mark_expired(none_io.query, none_io.write, NOW, 24), none_io.written), (0, []))

# --- 정상 조사 ---
io = FakeIO([anomaly("a-1")])
model = FakeModel(*GOOD)
clock = iter([datetime(2026, 10, 21, 10, 0, 0), datetime(2026, 10, 21, 10, 0, 5), datetime(2026, 10, 21, 10, 0, 6)])
res = run_one(anomaly("a-1"), io.query, io.write, model, lambda: next(clock))
tables = [t for t, _ in io.written]
check("정상: 리포트와 실행 기록을 한 줄씩 쌓음 (리포트 먼저)", tables, ["investigation_reports", "investigation_runs"])
rep, run = io.written[0][1][0], io.written[1][1][0]
check("정상: 리포트 줄에 원인 층, 사실/추정이 든 주장(JSON), 모델 ID, 조사 실행 번호", (rep["cause_layer"], json.loads(rep["claims"])[0]["kind"], rep["model_id"], rep["investigation_run_id"] == run["run_id"]), ("PAYMENT", "FACT", "fake-model", True))
check("정상: 실행 기록의 상태·횟수 (REPORTED, 모델 2번, 조회 도구 1번, 되돌림 0번)", (run["status"], run["turns"], run["tool_calls"], run["rejected_submissions"]), ("REPORTED", 2, 1, 0))
check("정상: 실행 기록에 시작·끝 시각과 리포트 번호", (run["started_at"], run["finished_at"], run["report_id"] == rep["report_id"]), (datetime(2026, 10, 21, 10, 0, 0), datetime(2026, 10, 21, 10, 0, 5), True))
check("정상: 문제가 없으면 problems는 NULL", rep["problems"], None)
check("정상: 조사 과정(trace)이 JSON으로 남음", json.loads(rep["trace"])[0]["tool"], "payment_summary")

# --- 검사를 못 통과한 리포트 ---
bad = dict(REPORT, claims=[{"text": "근거 없음", "kind": "FACT", "evidence": []}])
io = FakeIO([])
model = FakeModel([use(1, "payment_summary", **W)], [use(2, "submit_report", **bad)], [use(3, "submit_report", **bad)], [use(4, "submit_report", **bad)])
res = run_one(anomaly("a-1"), io.query, io.write, model, lambda: NOW)
run = io.written[1][1][0]
check("검사를 계속 못 통과하면 INCOMPLETE, problems가 남고 되돌림 횟수가 기록됨", (run["status"], run["rejected_submissions"], io.written[0][1][0]["problems"] is not None), ("INCOMPLETE", 2, True))

# --- 오류 ---
class Boom(FakeModel):
    def __call__(self, *a):
        raise RuntimeError("Bedrock 호출이 실패했습니다 (모델 x, 상태 429): slow")


io = FakeIO([])
res = run_one(anomaly("a-9"), io.query, io.write, Boom(), lambda: NOW)
check("오류로 끝나도 실행 기록(ERROR, 짧은 오류)을 남기고 리포트는 안 씀", ([t for t, _ in io.written], io.written[0][1][0]["status"], "RuntimeError" in io.written[0][1][0]["error"]), (["investigation_runs"], "ERROR", True))
check("실행 기록의 오류 메시지에 쿼리 문장이 들어가지 않음", "SELECT" in io.written[0][1][0]["error"], False)

# --- 진입점 ---
io = FakeIO([anomaly("a-1"), anomaly("a-2")])
model = FakeModel(*GOOD, *GOOD)
s = main(env={"INVESTIGATE_MAX": "1"}, io=io, converse=model, now_fn=lambda: NOW)
check("진입점: 상한(1개)만큼만 조사하고 요약을 돌려줌", (s["found"], len(s["results"]), s["results"][0]["status"], s["model_id"]), (1, 1, "REPORTED", "fake-model"))
try:
    main(env={}, io=None, converse=model)
    check("진입점: workgroup이 없으면 종료", "통과됨", "종료")
except SystemExit:
    check("진입점: workgroup이 없으면 종료", "종료", "종료")
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
