"""읽기 전용 도구 시험. sqlite 가짜 원장으로 돌린다 (Athena는 아직 안 돌려봤다).

실행: python3 test_tools.py
"""
import sqlite3
from datetime import datetime

import guard
from guard import GuardError, validate_sql
from ledger_tools import TOOL_SPECS, run_tool

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


def rejects(name, fn):
    global ok
    try:
        fn()
    except GuardError as e:
        print(f"통과 {name} | 막힌 이유: {e}")
    else:
        ok = False
        print(f"실패 {name} | 막혔어야 하는데 통과함")


def build():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ':memory:' AS gold_b")
    con.executescript("""
    CREATE TABLE gold_b.payment_attempts (payment_id, order_id, attempt_no, pg, status, failure_code, failure_cause, completed_at, loaded_at);
    CREATE TABLE gold_b.payment_events (payment_id, completed_at);
    CREATE TABLE gold_b.topic_messages (topic, kafka_partition, kafka_offset, kafka_timestamp, loaded_at);
    CREATE TABLE gold_b.bronze_lag_snapshots (collected_at, topic, "partition", end_offset, committed_offset, lag_msgs, lag_sec, connector_state);
    CREATE TABLE gold_b.malformed_events (topic, kafka_partition, kafka_offset, kafka_timestamp, field, reason, raw_sample, rule_version, loaded_at);
    CREATE TABLE gold_b.malformed_messages (topic, kafka_partition, kafka_offset, rule_version, kafka_timestamp, error_count, reason, loaded_at);
    CREATE TABLE gold_b.reprocess_events (request_id, step, at, actor, window_start, window_end, source, attempt, detail);
    CREATE TABLE gold_b.anomaly (run_id, anomaly_id, rule_id, rule_version, anomaly_type, scope_key, window_start, window_end,
                                 metric, observed_value, baseline_value, sample_size, episode_start, episode_end, status);
    """)
    pay = [  # PG_A에서 PG 원인 실패 3건, 고객 원인 1건, 성공 2건. PG_B는 성공 2건
        ("p1", "o1", 1, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-20 15:01:00"),
        ("p2", "o1", 2, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-20 15:02:00"),
        ("p3", "o2", 1, "PG_A", "FAILED", "PG_ERROR", "PG", "2026-10-20 15:03:00"),
        ("p4", "o3", 1, "PG_A", "FAILED", "CARD_DECLINED", "CUSTOMER", "2026-10-20 15:04:00"),
        ("p5", "o4", 1, "PG_A", "SUCCESS", None, None, "2026-10-20 15:05:00"),
        ("p6", "o5", 1, "PG_A", "SUCCESS", None, None, "2026-10-20 15:06:00"),
        ("p7", "o6", 1, "PG_B", "SUCCESS", None, None, "2026-10-20 15:02:00"),
        ("p8", "o7", 1, "PG_B", "SUCCESS", None, None, "2026-10-20 15:03:00"),
    ]
    con.executemany("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)", [r + ("2026-10-20 15:10:00",) for r in pay])
    con.executemany("INSERT INTO gold_b.payment_events VALUES (?,?)", [(r[0], r[7]) for r in pay] + [("p1", "2026-10-20 15:01:00")])  # p1 중복 1건
    msgs = [("orders", 0, off, f"2026-10-20 15:0{off % 6}:00", "2026-10-20 15:10:00") for off in (0, 1, 2, 5, 6)]  # 3, 4번 누락 (2칸)
    msgs += [("clickstream", 1, off, "2026-10-20 15:03:00", "2026-10-20 15:10:00") for off in range(4)]
    msgs += [("orders", 0, 6, "2026-10-20 15:00:00", "2026-10-20 15:10:00")]  # offset 6 중복
    con.executemany("INSERT INTO gold_b.topic_messages VALUES (?,?,?,?,?)", msgs)
    lag = [("2026-10-20 15:09:00", "orders", 0, 100, 40, 60, 90.0, "RUNNING"),
           ("2026-10-20 15:10:00", "orders", 0, 130, 40, 90, 150.0, "RUNNING"),   # 처리 위치가 40에서 멈춤
           ("2026-10-20 15:10:00", "payments", 0, 50, 50, 0, 0.5, "RUNNING")]
    con.executemany("INSERT INTO gold_b.bronze_lag_snapshots VALUES (?,?,?,?,?,?,?,?)", lag)
    mal = [("clickstream", 1, 10, "2026-10-20 15:04:00", "session_id", "MISSING_FIELD", "원문 일부", "v1.0", "2026-10-20 15:10:00"),
           ("clickstream", 1, 10, "2026-10-20 15:04:00", "article_id", "TYPE_MISMATCH", None, "v1.0", "2026-10-20 15:10:00"),
           ("clickstream", 1, 11, "2026-10-20 15:05:00", "session_id", "MISSING_FIELD", "원문 일부", "v1.0", "2026-10-20 15:10:00"),
           ("clickstream", 1, 12, "2026-10-20 15:06:00", "session_id", "MISSING_FIELD", "원문 일부", "v0.9", "2026-10-20 15:10:00")]  # 옛 버전
    con.executemany("INSERT INTO gold_b.malformed_events VALUES (?,?,?,?,?,?,?,?,?)", mal)
    con.executemany("INSERT INTO gold_b.malformed_messages VALUES (?,?,?,?,?,?,?,?)", [
        ("clickstream", 1, 10, "v1.0", "2026-10-20 15:04:00", 2, "MISSING_FIELD", "2026-10-20 15:10:00"),
        ("clickstream", 1, 11, "v1.0", "2026-10-20 15:05:00", 1, "MISSING_FIELD", "2026-10-20 15:10:00"),
        ("clickstream", 1, 12, "v0.9", "2026-10-20 15:06:00", 1, "MISSING_FIELD", "2026-10-20 15:10:00")])
    con.executemany("INSERT INTO gold_b.reprocess_events VALUES (?,?,?,?,?,?,?,?,?)", [
        ("rq-1", "REQUESTED", "2026-10-20 16:00:00", "jh", "2026-10-20 15:00:00", "2026-10-20 15:30:00", None, 1, None),
        ("rq-1", "APPROVED", "2026-10-20 16:01:00", "jh", "2026-10-20 15:00:00", "2026-10-20 15:30:00", None, 1, None)])
    con.executemany("INSERT INTO gold_b.anomaly VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("r1", "a-1", "R1", "v0.1", "PG_FAILURE_SPIKE", "pg=PG_A", "2026-10-20 15:00:00", "2026-10-20 15:15:00", "pg_cause_failures", 3, 3, 6, None, None, "OPEN"),
        ("r2", "a-1", "R1", "v0.1", "PG_FAILURE_SPIKE", "pg=PG_A", "2026-10-20 15:00:00", "2026-10-20 15:15:00", "pg_cause_failures", 3, 3, 6, None, None, "OPEN")])
    return con


con = build()


def execute(sql):
    return [dict(r) for r in con.execute(sql).fetchall()]


W = dict(window_start="2026-10-20T15:00:00", window_end="2026-10-20T16:00:00")


def run(name, **args):
    return run_tool(name, args, execute, dialect="sqlite", now=datetime(2026, 10, 20, 15, 11, 0))


# --- 도구가 맞는 숫자를 돌려주는가 ---
rows = {r["pg"]: r for r in run("payment_summary", **W)["rows"]}
check("결제 요약: PG_A 시도 6, 실패 4, PG 원인 3, 고객 원인 1", (rows["PG_A"]["attempts"], rows["PG_A"]["failures"], rows["PG_A"]["pg_cause_failures"], rows["PG_A"]["customer_cause_failures"]), (6, 4, 3, 1))
check("결제 요약: PG_B는 실패 0", (rows["PG_B"]["attempts"], rows["PG_B"]["failures"]), (2, 0))
check("결제 요약: pg 지정하면 그 PG만", [r["pg"] for r in run("payment_summary", pg="PG_B", **W)["rows"]], ["PG_B"])
codes = {r["failure_code"]: r["n"] for r in run("payment_failure_codes", pg="PG_A", **W)["rows"]}
check("실패 코드: PG_TIMEOUT 2, PG_ERROR 1, CARD_DECLINED 1", codes, {"PG_TIMEOUT": 2, "PG_ERROR": 1, "CARD_DECLINED": 1})
impact = run("payment_retry_impact", pg="PG_A", **W)["rows"][0]
check("재시도 영향: PG 원인 실패 겪은 주문 2, 재시도 1", (impact["orders_with_pg_failure"], impact["retry_attempts"]), (2, 1))
vol = {r["topic"]: r["messages"] for r in run("ingest_volume", **W)["rows"]}
check("유입량: orders 6, clickstream 4", vol, {"orders": 6, "clickstream": 4})
lg = run("bronze_lag", topic="orders", **W)["rows"][0]
check("Bronze 지연: 최대 150초, 처리 위치 40에서 안 움직임", (lg["max_lag_sec"], lg["min_committed_offset"], lg["max_committed_offset"]), (150.0, 40, 40))
ms = run("malformed_summary", rule_version="v1.0", **W)["rows"]
check("깨진 메시지: 사유별 메시지 수, 현재 규칙 v1.0만 (옛 v0.9 제외). 사유는 오류 단위 원장에서 읽음", [(r["reason"], r["broken_messages"]) for r in ms], [("MISSING_FIELD", 2), ("TYPE_MISMATCH", 1)])
mf = {(r["field"], r["reason"]): (r["errors"], r["earliest_offset"]) for r in run("malformed_fields", rule_version="v1.0", **W)["rows"]}
check("깨진 필드: session_id 2건(가장 이른 offset 10), article_id 1건", mf, {("session_id", "MISSING_FIELD"): (2, 10), ("article_id", "TYPE_MISMATCH"): (1, 10)})
rel = run("ledger_reliability", **W)
check("신뢰성: orders 파티션 0에서 2칸 누락", [(g["topic"], g["missing_count"]) for g in rel["missing_messages"]], [("orders", 2)])
check("신뢰성: 메시지 중복 1, 결제 중복(참고값) 1", (rel["duplicate_messages"], rel["payment_duplicate_rows_info"]), (1, 1))
check("신뢰성: 적재 잡은 1분 전까지 썼으므로 OK, 수집기도 1분 전이라 OK", (rel["ledger_writer"]["status"], rel["lag_collector"]["status"]), ("OK", "OK"))
late = run_tool("ledger_reliability", W, execute, dialect="sqlite", now=datetime(2026, 10, 20, 15, 14, 0))
check("신뢰성: 4분 동안 안 쓰면 STOPPED", (late["ledger_writer"]["status"], late["lag_collector"]["status"]), ("STOPPED", "STOPPED"))
an = run("list_anomalies", **W)["rows"]
check("이상 이력: 같은 이상이 2회차(r2가 앞)로 나옴", [r["run_id"] for r in an], ["r2", "r1"])
check("재처리 상태: 최근 단계가 APPROVED", run("reprocess_status", request_id="rq-1")["rows"][0]["step"], "APPROVED")

# 데이터 오염: o4(성공 1건)에 성공을 한 건 더, 결제 시각은 과거(14:30), 적재는 15:10. o1은 실패 뒤 재시도라 SUCCESS가 없다.
con.execute("INSERT INTO gold_b.payment_attempts VALUES ('d1','o4',2,'PG_A','SUCCESS',NULL,NULL,'2026-10-20 14:30:02','2026-10-20 15:10:00')")
dup = run("duplicate_success_orders", **W)["rows"]
check("성공 결제 중복: o4 하나, 성공 2건 (결제 시각이 구간 밖이어도 적재 시각으로 잡음)", [(r["order_id"], r["success_count"]) for r in dup], [("o4", 2)])
EARLY = dict(window_start="2026-10-20T14:00:00", window_end="2026-10-20T15:00:00")
check("성공 결제 중복: 14시대를 적재 시각으로 보면 없고, 결제 시각으로 보면 o4(중복 행이 14:30)",
      ([r["order_id"] for r in run("duplicate_success_orders", **EARLY)["rows"]], [r["order_id"] for r in run("duplicate_success_orders", time_basis="completed_at", **EARLY)["rows"]]), ([], ["o4"]))
rejects("모르는 time_basis 막힘", lambda: run("duplicate_success_orders", time_basis="x; DROP", **W))


# --- 재영 님 리뷰 반영 ---
from guard import parse_time, GuardError as _GE
check("시각: Z와 +00:00과 시간대 없음은 모두 같은 UTC 시각", (parse_time("2026-10-20T15:00:00Z"), parse_time("2026-10-20T15:00:00+00:00"), parse_time("2026-10-20 15:00:00")), (datetime(2026, 10, 20, 15),) * 3)
check("시각: +09:00은 UTC로 바꿈 (9시간 빼기)", parse_time("2026-10-21T00:00:00+09:00"), datetime(2026, 10, 20, 15))
sql_kst = run("payment_summary", window_start="2026-10-21T00:00:00+09:00", window_end="2026-10-21T01:00:00+09:00")
check("시각: 조회 구간을 +09:00으로 줘도 UTC 구간(15시대)을 조회함", len(sql_kst["rows"]) >= 0 and run("payment_summary", window_start="2026-10-20T15:00:00Z", window_end="2026-10-20T16:00:00+00:00")["rows"] == run("payment_summary", window_start="2026-10-21T00:00:00+09:00", window_end="2026-10-21T01:00:00+09:00")["rows"], True)
check("시각: Z와 +00:00을 섞어 시작·끝을 줘도 오류 없음", len(run("payment_summary", window_start="2026-10-20T15:00:00Z", window_end="2026-10-20T16:00:00+00:00")["rows"]) > 0, True)
rejects("시각: 형식이 틀리면 막힘", lambda: parse_time("어제 3시"))
check("신뢰성: 누락 검사는 부분 확인(PARTIAL)이라고 알려 줌", (rel["completeness"], "빠진 것은 찾지 못" in rel["completeness_note"]), ("PARTIAL", True))
check("신뢰성: 메시지가 없던 파티션 목록을 알려 줌 (orders 0, clickstream 1만 있음 -> 13개)", (len(rel["partitions_without_messages"]), {"topic": "orders", "partition": 0} in rel["partitions_without_messages"]), (13, False))
con.execute("DELETE FROM gold_b.topic_messages"); con.execute("DELETE FROM gold_b.bronze_lag_snapshots")
empty = run("ledger_reliability", **W)
check("신뢰성: 표가 비어 있으면 정상(OK)이 아니라 NO_DATA", (empty["ledger_writer"]["status"], empty["lag_collector"]["status"], empty["completeness"], empty["messages_in_window"]), ("NO_DATA", "NO_DATA", "NO_DATA", 0))

# --- 울타리가 막는가 ---
rejects("INSERT 막힘", lambda: validate_sql("INSERT INTO gold_b.anomaly VALUES (1) LIMIT 1"))
rejects("DROP 막힘", lambda: validate_sql("SELECT 1 FROM gold_b.anomaly; DROP TABLE gold_b.anomaly LIMIT 1"))
rejects("정답표 폴더 막힘", lambda: validate_sql("SELECT * FROM ground_truth.incident_log LIMIT 10"))
rejects("허용 목록 밖 표 막힘", lambda: validate_sql("SELECT * FROM silver.orders_current LIMIT 10"))
rejects("원문 일부(raw_sample) 막힘", lambda: validate_sql("SELECT raw_sample FROM gold_b.malformed_events LIMIT 10"))
rejects("LIMIT 없으면 막힘", lambda: validate_sql("SELECT * FROM gold_b.anomaly"))
rejects("LIMIT 너무 크면 막힘", lambda: validate_sql("SELECT * FROM gold_b.anomaly LIMIT 100000"))
rejects("6시간 넘는 범위 막힘", lambda: run("payment_summary", window_start="2026-10-20T00:00:00", window_end="2026-10-20T12:00:00"))
rejects("끝이 시작보다 앞이면 막힘", lambda: run("payment_summary", window_start="2026-10-20T16:00:00", window_end="2026-10-20T15:00:00"))
rejects("모르는 PG 이름 막힘", lambda: run("payment_summary", pg="PG_C'; DROP TABLE x; --", **W))
rejects("이상한 request_id 막힘", lambda: run("reprocess_status", request_id="rq-1' OR '1'='1"))
rejects("없는 도구 막힘", lambda: run("delete_everything"))
check("도구 정의 11개", len(TOOL_SPECS), 11)
check("모든 도구가 SELECT만 만든다 (울타리 통과)", all(
    validate_sql(sql) for name, (b, _) in __import__("ledger_tools").TOOLS.items()
    for _, sql in b({**W, "request_id": "rq-1", "rule_version": "v1.0"}, "athena")), True)
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
