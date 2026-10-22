"""재처리 승인 백엔드 규칙 시험. sqlite 가짜 표와 가짜 Airflow로 돌린다 (진짜 Athena·Airflow는 아직 안 돌려 봤다).

실행: python3 test_approval.py
"""
import json
import sqlite3
import urllib.error
from datetime import datetime, timedelta

from approval import (ApprovalConfig, ApprovalError, AirflowClient, approve, check_actor, derive_state, fetch_rows, latest_row, reject,
                      request_reprocess, start_run)

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


def code(fn):
    try:
        fn()
    except ApprovalError as error:
        return error.code
    return None


COLS = ("request_id", "step", "at", "actor", "reason", "window_start", "window_end", "rule_version", "source", "attempt", "parent_request_id", "detail")
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.execute("ATTACH DATABASE ':memory:' AS gold_b")
con.execute("CREATE TABLE gold_b.reprocess_events (" + ", ".join(COLS) + ")")


def query(sql):
    return [dict(r) for r in con.execute(sql).fetchall()]


def write(table, rows):
    assert table == "reprocess_events"
    for r in rows:
        con.execute("INSERT INTO gold_b.reprocess_events VALUES (" + ",".join("?" * len(COLS)) + ")", [r[c] for c in COLS])


def steps(rid):
    return [r["step"] for r in query(f"SELECT step FROM gold_b.reprocess_events WHERE request_id = '{rid}' ORDER BY at, rowid")]


CFG = ApprovalConfig(dialect="sqlite", dag_by_rule={"R6_ORDER_TOTAL_MISMATCH": ("silver_gold_a_reprocess", "SILVER"),
                                                    "R1_PG_FAILURES": ("gold_b_reprocess", "KAFKA"), "R5_DUPLICATE_SUCCESS": (None, "KAFKA")})
T0 = datetime(2026, 10, 22, 15, 30, 0)
R1 = {"anomaly_id": "a1", "rule_id": "R1_PG_FAILURES", "window_start": "2026-10-22 15:10:00", "window_end": "2026-10-22 15:25:00", "evidence_ref": "{}"}
R6 = {"anomaly_id": "a6", "rule_id": "R6_ORDER_TOTAL_MISMATCH", "window_start": "2026-10-22 15:00:00", "window_end": "2026-10-22 15:30:00",
      "evidence_ref": json.dumps({"new_orders": ["o1", "o2"]})}
ME = "jh@example.com"

calls = []


def trigger_ok(dag_id, run_id, conf):
    calls.append((dag_id, run_id, conf))
    return 200


# --- 승인자 ---
check("승인자: 빈 값, 개발용 사용자, 이메일이 아닌 값은 거부", [code(lambda a=a: check_actor(a)) for a in ("", None, "dev-user", "홍길동")], ["ACTOR_REQUIRED"] * 4)
check("승인자: 이메일은 통과", check_actor(" jh@example.com "), "jh@example.com")

# --- 요청 ---
check("요청: 재처리 DAG가 아직 정해지지 않은 규칙은 거절", code(lambda: request_reprocess(dict(R1, rule_id="R5_DUPLICATE_SUCCESS"), "rep-1", ME, T0, query, write, CFG)), "DAG_NOT_CONFIGURED")
check("요청: 재처리 대상이 아닌 규칙(R3)은 거절", code(lambda: request_reprocess(dict(R1, rule_id="R3_BRONZE_LAG"), "rep-1", ME, T0, query, write, CFG)), "NOT_REPROCESSABLE")
check("요청: 승인자 없이는 거절", code(lambda: request_reprocess(R1, "rep-1", "dev-user", T0, query, write, CFG)), "ACTOR_REQUIRED")
r = request_reprocess(R1, "rep-1", ME, T0, query, write, CFG)
rid1 = r["request_id"]
row = fetch_rows(query, rid1)[0]
check("요청: REQUESTED 줄이 쌓이고 상태는 REQUESTED", (steps(rid1), r["state"], row["actor"]), (["REQUESTED"], "REQUESTED", ME))
check("요청: Gold B 원장(KAFKA)은 1시간 폴더 단위라 시간대를 정시로 넓힘", (row["window_start"], row["window_end"], row["source"]), ("2026-10-22 15:00:00", "2026-10-22 16:00:00", "KAFKA"))
check("요청: 상세에 이상·리포트·DAG가 남음", {k: json.loads(row["detail"])[k] for k in ("anomaly_id", "report_id", "dag_id")}, {"anomaly_id": "a1", "report_id": "rep-1", "dag_id": "gold_b_reprocess"})
check("요청: 같은 이상에 진행 중인 요청이 있으면 중복 요청 거절", code(lambda: request_reprocess(R1, "rep-1", ME, T0 + timedelta(minutes=5), query, write, CFG)), "DUPLICATE_REQUEST")
check("요청: 만료된 뒤에는 새로 요청할 수 있음", request_reprocess(R1, "rep-1", ME, T0 + timedelta(minutes=61), query, write, CFG)["state"], "REQUESTED")
r6 = request_reprocess(R6, "rep-6", ME, T0, query, write, CFG)
row6 = fetch_rows(query, r6["request_id"])[0]
check("요청: R6는 Silver 기준(시간대 그대로, 주문 id 목록)이고 재처리로 안 풀릴 수 있다는 경고가 붙음",
      (row6["source"], row6["window_start"], json.loads(row6["detail"])["order_ids"], r6["warning"]), ("SILVER", "2026-10-22 15:00:00", ["o1", "o2"], "UNFIXABLE_BY_REPROCESS"))
check("요청: R1은 재처리로 풀릴 수 있어 경고 없음", r["warning"], None)
check("요청: 재시도가 한도(2번)를 넘으면 거절", code(lambda: request_reprocess(dict(R1, anomaly_id="a9"), "rep-9", ME, T0, query, write, CFG, attempt=4)), "TOO_MANY_ATTEMPTS")
check("요청: 이상 id에 따옴표 같은 글자가 있으면 거절(쿼리 주입 방지)", code(lambda: request_reprocess(dict(R1, anomaly_id="a' OR '1'='1"), "rep-1", ME, T0, query, write, CFG)), "BAD_ID")

# --- 승인 ---
check("승인: 승인자 없이는 거절", code(lambda: approve(rid1, "", T0, query, write, trigger_ok, CFG)), "ACTOR_REQUIRED")
check("승인: 없는 요청은 거절", code(lambda: approve("rq-none", ME, T0, query, write, trigger_ok, CFG)), "BAD_STATE")
check("승인: 요청 id에 따옴표가 있으면 거절", code(lambda: approve("x'; DROP", ME, T0, query, write, trigger_ok, CFG)), "BAD_ID")
res = approve(rid1, ME, T0 + timedelta(minutes=10), query, write, trigger_ok, CFG)
check("승인: APPROVED 줄이 쌓이고 DAG를 한 번 부름", (steps(rid1), res["airflow"], len(calls)), (["REQUESTED", "APPROVED"], "TRIGGERED", 1))
dag_id, run_id, conf = calls[0]
check("승인: dag_run_id가 request_id, DAG ID는 요청 때 정한 것", (dag_id, run_id), ("gold_b_reprocess", rid1))
check("승인: 호출 입력(conf)에 요청 id·시간대·규칙 버전·이상 id·리포트 id가 있고, R1에는 주문 id 목록이 없음",
      ({k: conf[k] for k in ("request_id", "window_start", "window_end", "rule_version", "anomaly_id", "report_id")}, "order_ids" in conf),
      ({"request_id": rid1, "window_start": "2026-10-22 15:00:00", "window_end": "2026-10-22 16:00:00", "rule_version": "0.2.0", "anomaly_id": "a1", "report_id": "rep-1"}, False))
check("승인 줄에 승인자가 남음", json.loads(fetch_rows(query, rid1)[-1]["detail"])["approved_by"], ME)


def trigger_409(dag_id, run_id, conf):
    calls.append("409")
    return 409


res = approve(rid1, ME, T0 + timedelta(minutes=11), query, write, trigger_409, CFG)
check("중복 승인: 이미 승인된 요청은 승인 줄을 다시 쓰지 않고, Airflow가 409로 막으면 '이미 시작됨'으로 처리", (steps(rid1), res["airflow"]), (["REQUESTED", "APPROVED"], "ALREADY_TRIGGERED"))
write("reprocess_events", [dict(row, step="STARTED", at=(T0 + timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S"), actor="reprocess_job", detail="{}")])
check("중복 승인: DAG가 시작(STARTED)한 뒤에는 승인할 수 없음", code(lambda: approve(rid1, ME, T0 + timedelta(minutes=13), query, write, trigger_ok, CFG)), "BAD_STATE")

# Airflow 실패와 재시도
rf = request_reprocess(dict(R1, anomaly_id="a2"), "rep-2", ME, T0, query, write, CFG)["request_id"]
check("Airflow가 실패하면 오류를 알리고 APPROVED 줄은 남음", (code(lambda: approve(rf, ME, T0 + timedelta(minutes=1), query, write, lambda *a: 500, CFG)), steps(rf)), ("AIRFLOW_FAILED", ["REQUESTED", "APPROVED"]))
check("Airflow 실패 뒤 같은 승인으로 다시 시도하면 성공하고 승인 줄은 늘지 않음", (approve(rf, ME, T0 + timedelta(minutes=2), query, write, trigger_ok, CFG)["airflow"], steps(rf)), ("TRIGGERED", ["REQUESTED", "APPROVED"]))

# 만료
re_ = request_reprocess(dict(R1, anomaly_id="a3"), "rep-3", ME, T0, query, write, CFG)["request_id"]
check("만료: 요청 후 60분이 지나면 승인할 수 없음", code(lambda: approve(re_, ME, T0 + timedelta(minutes=61), query, write, trigger_ok, CFG)), "BAD_STATE")
ra = request_reprocess(dict(R1, anomaly_id="a4"), "rep-4", ME, T0, query, write, CFG)["request_id"]
try:
    approve(ra, ME, T0 + timedelta(minutes=1), query, write, lambda *a: 500, CFG)
except ApprovalError:
    pass
check("만료: 승인 후 60분이 지나도록 시작하지 못하면 다시 시작할 수 없음", code(lambda: start_run(ra, T0 + timedelta(minutes=62), query, trigger_ok, CFG)), "BAD_STATE")

# 거절
rr = request_reprocess(dict(R1, anomaly_id="a5"), "rep-5", ME, T0, query, write, CFG)["request_id"]
check("거절: REJECTED 줄에 사유가 남음", (reject(rr, ME, "원본 수정이 먼저", T0 + timedelta(minutes=1), query, write, CFG)["state"], fetch_rows(query, rr)[-1]["reason"]), ("REJECTED", "원본 수정이 먼저"))
check("거절: 거절한 요청은 승인할 수 없음", code(lambda: approve(rr, ME, T0 + timedelta(minutes=2), query, write, trigger_ok, CFG)), "BAD_STATE")
check("거절: 이미 승인된 요청은 거절할 수 없음", code(lambda: reject(rid1, ME, "", T0 + timedelta(minutes=14), query, write, CFG)), "BAD_STATE")

# R6 입력에는 주문 id가 실림
calls.clear()
approve(r6["request_id"], ME, T0 + timedelta(minutes=3), query, write, trigger_ok, CFG)
check("R6 승인: 호출 입력에 주문 id 목록이 실리고 DAG는 silver_gold_a_reprocess", (calls[0][0], calls[0][2]["order_ids"]), ("silver_gold_a_reprocess", ["o1", "o2"]))

# 상태 계산
def at(m):
    return (T0 + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S")


same = [dict(row, step="REDETECTED", at=at(5)), dict(row, step="VERIFIED", at=at(5))]
check("상태: 같은 시각에 두 줄이면 단계 순서로 뒤의 VERIFIED가 최근", (latest_row(same)["step"], derive_state(same, T0 + timedelta(hours=5), CFG)), ("VERIFIED", "VERIFIED"))
check("상태: 줄이 없으면 None", derive_state([], T0, CFG), None)


# --- Airflow 호출기 ---
class Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


seen = []


def opener_ok(req, timeout=None):
    seen.append((req.full_url, req.get_method(), dict(req.header_items()), json.loads(req.data)))
    if req.full_url.endswith("/auth/token"):
        return Resp(201, b'{"access_token": "TOK"}')
    return Resp(200, b"{}")


client = AirflowClient("http://airflow.test:8080/", "approval", "PW", opener=opener_ok)
check("Airflow 호출기: 토큰을 받고 dagRuns를 부름(logical_date 없음, dag_run_id 지정)", client.trigger("silver_gold_a_reprocess", "rq-1", {"a": 1}), 200)
check("Airflow 호출기: 주소와 본문", ([s[0] for s in seen], seen[1][3]), (["http://airflow.test:8080/auth/token", "http://airflow.test:8080/api/v2/dags/silver_gold_a_reprocess/dagRuns"],
                                                                      {"logical_date": None, "dag_run_id": "rq-1", "conf": {"a": 1}}))
check("Airflow 호출기: 두 번째 요청에만 Bearer 토큰", ("Authorization" in seen[0][2], seen[1][2].get("Authorization")), (False, "Bearer TOK"))


def opener_409(req, timeout=None):
    if req.full_url.endswith("/auth/token"):
        return Resp(201, b'{"access_token": "TOK"}')
    raise urllib.error.HTTPError(req.full_url, 409, "dup", {}, None)


def opener_login_fail(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)


def opener_down(req, timeout=None):
    raise urllib.error.URLError("연결 안 됨")


check("Airflow 호출기: 같은 dag_run_id는 409를 돌려줌", AirflowClient("http://x", "u", "p", opener=opener_409).trigger("d", "r", {}), 409)
check("Airflow 호출기: 로그인 실패는 401, 연결 실패는 0", (AirflowClient("http://x", "u", "p", opener=opener_login_fail).trigger("d", "r", {}), AirflowClient("http://x", "u", "p", opener=opener_down).trigger("d", "r", {})), (401, 0))
check("Airflow 호출기: 잘못된 DAG ID·실행 ID는 호출 전에 거절", (code(lambda: client.trigger("d/../x", "r", {})), code(lambda: client.trigger("d", "r;x", {}))), ("BAD_ID", "BAD_ID"))

# --- 은서 님 워크플로우: gold_b_reprocess가 5분마다 APPROVED를 읽음(POLLER) ---
DEFAULT = ApprovalConfig(dialect="sqlite")
check("기본 설정: Gold B 규칙(R1·R4·R5)은 POLLER, R6는 Silver DAG, 규칙 버전 0.2.0", ([DEFAULT.dag_by_rule[k][0] for k in ("R1_PG_FAILURES", "R4_MALFORMED", "R5_DUPLICATE_SUCCESS")], DEFAULT.dag_by_rule["R6_ORDER_TOTAL_MISMATCH"][0], DEFAULT.rule_version),
      (["POLLER"] * 3, "silver_gold_a_reprocess", "0.2.0"))
polled = []
rp = request_reprocess(dict(R1, anomaly_id="p1"), "rep-p", ME, T0, query, write, DEFAULT)["request_id"]
res = approve(rp, ME, T0 + timedelta(minutes=2), query, write, lambda *a: polled.append(a) or 200, DEFAULT)
check("POLLER: 승인하면 APPROVED 줄만 쓰고 Airflow는 부르지 않음", (steps(rp), res["airflow"], polled), (["REQUESTED", "APPROVED"], "POLLER", []))
res = approve(rp, ME, T0 + timedelta(minutes=3), query, write, lambda *a: polled.append(a) or 200, DEFAULT)
check("POLLER: 다시 승인해도 승인 줄이 늘지 않고 호출도 없음", (steps(rp), res["airflow"], polled), (["REQUESTED", "APPROVED"], "POLLER", []))
old = request_reprocess(dict(R1, anomaly_id="p2", window_start="2026-10-10 10:00:00", window_end="2026-10-10 10:15:00"), "rep-p2", ME, T0, query, write, DEFAULT)
check("Kafka 보관 기간(3일)을 넘긴 구간은 경고(요청은 받음)", old["warnings"], ["OUTSIDE_KAFKA_RETENTION"])
check("최근 구간의 R1은 경고 없음", request_reprocess(dict(R1, anomaly_id="p3"), "rep-p3", ME, T0, query, write, DEFAULT)["warnings"], [])
check("Silver(R6)는 보관 기간 경고가 없고 재처리로 안 풀릴 수 있다는 경고만", request_reprocess(dict(R6, anomaly_id="p6"), "rep-p6", ME, T0, query, write, DEFAULT)["warnings"], ["UNFIXABLE_BY_REPROCESS"])

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
