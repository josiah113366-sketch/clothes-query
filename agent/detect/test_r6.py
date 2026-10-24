"""규칙 R6(Silver 주문 총액 불일치) 시험. 가짜 Silver 검사 결과와 가짜 이상 이력으로 순찰을 돌려 본다.

Silver 결과가 Athena 표로 제공되는지, 표 이름은 무엇인지는 아직 정해지지 않았다. 이 시험은 Silver 담당의 제공안(컬럼, 상태)을 그대로 가정한다.
실행: python3 test_r6.py
"""
import json
import sqlite3
from datetime import datetime

from job import regular_run, run_once
from rules import R6_RULE, Config, open_orders

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


F = "%Y-%m-%d %H:%M:%S"
TABLE = "silver.order_total_checks"
CFG = Config(dialect="sqlite", silver_checks_table=TABLE, lag_sec=60.0, format_rule_version="v1.0")


def build():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ':memory:' AS gold_b")
    con.execute("ATTACH DATABASE ':memory:' AS silver")
    con.executescript("""
    CREATE TABLE gold_b.payment_attempts (payment_id, order_id, attempt_no, pg, status, failure_code, failure_cause, completed_at, loaded_at);
    CREATE TABLE gold_b.topic_messages (topic, kafka_partition, kafka_offset, kafka_timestamp, loaded_at);
    CREATE TABLE gold_b.bronze_lag_snapshots (collected_at, topic, "partition", end_offset, committed_offset, lag_msgs, lag_sec, connector_state);
    CREATE TABLE gold_b.malformed_messages (topic, kafka_partition, kafka_offset, rule_version, kafka_timestamp, error_count, reason, loaded_at);
    CREATE TABLE gold_b.reprocess_events (request_id, step, at, actor, reason, window_start, window_end, rule_version, source, attempt, parent_request_id, detail);
    CREATE TABLE gold_b.anomaly (run_id, anomaly_id, rule_id, rule_version, anomaly_type, source_table, window_start, window_end, scope_type, scope_key,
                                 metric, observed_value, baseline_value, baseline_kind, sample_size, episode_start, episode_end, evidence_ref, status, detected_at);
    CREATE TABLE gold_b.detection_runs (run_id, kind, request_id, judged_from, judged_to, started_at, anomaly_count);
    CREATE TABLE silver.silver_runs (run_id, completed_at, status, quality_status);
    CREATE TABLE silver.order_total_checks (run_id, checked_at, order_id, check_name, check_version, status, order_total_amount, item_total_amount, amount_difference, source_manifest);
    """)
    return con


con = build()


def query(sql):
    return [dict(r) for r in con.execute(sql).fetchall()]


def write(table, rows):
    for r in rows:
        con.execute(f"INSERT INTO gold_b.{table} ({','.join(r)}) VALUES ({','.join('?' * len(r))})", list(r.values()))


def silver(run, checked, rows, check="order_item_total_match"):
    """rows: [(주문, 상태, 주문 총액, 상품 합계)]"""
    for oid, status, total, items in rows:
        diff = None if items is None else items - total
        con.execute("INSERT INTO silver.order_total_checks VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run, checked, oid, check, "v1", status, total, items, diff, f"manifest-{run}"))


def r6(where=""):
    return query(f"SELECT * FROM gold_b.anomaly WHERE rule_id = '{R6_RULE}' {where} ORDER BY detected_at, scope_key")


def at(h, m=0):
    return datetime(2026, 10, 21, h, m)


# --- 설정이 없으면 돌리지 않는다 ---
silver("S1", "2026-10-21 14:00:00", [("o1", "MISMATCH", 30000, 20000), ("o2", "MISMATCH", 50000, 40000), ("o3", "MISMATCH", 10000, 11000), ("o4", "PASS", 5000, 5000)])
regular_run(query, write, Config(dialect="sqlite", lag_sec=60.0, format_rule_version="v1.0"), at(14, 12))
check("silver_checks_table이 없으면 R6을 돌리지 않음", len(r6()), 0)

# --- 첫 실행: 불일치 3건이 새 이상 ---
regular_run(query, write, CFG, at(14, 22))
rows = r6()
check("새 불일치 3건이 이상 줄 1개로 기록됨 (대상 orders, OPEN)", [(x["scope_key"], x["observed_value"], x["status"], x["anomaly_type"]) for x in rows], [("orders", 3, "OPEN", "ORDER_TOTAL_MISMATCH")])
ev = json.loads(rows[0]["evidence_ref"])
check("근거에 Silver 실행 번호, 검사 버전, 실행 참조, 주문 번호, 금액 차이가 들어감", (ev["silver_run_id"], ev["check_version"], ev["source_manifest"], ev["new_orders"], ev["total_abs_difference"], ev["max_abs_difference"]), ("S1", "v1", "manifest-S1", ["o1", "o2", "o3"], 21000, 10000))
check("이상 줄의 시각은 Silver 검사 시각", (rows[0]["window_start"], rows[0]["window_end"]), ("2026-10-21 14:00:00", "2026-10-21 14:00:00"))

# --- 같은 실행을 다시 읽어도 새 줄이 없다 (지속) ---
regular_run(query, write, CFG, at(14, 27))
check("같은 Silver 실행을 다시 읽어도 새 줄이 생기지 않음", len(r6()), 1)
check("열려 있는 주문은 이전 이상 줄의 근거에서 되살림", sorted(open_orders([r["evidence_ref"] for r in r6()])), ["o1", "o2", "o3"])

# --- 두 번째 실행: o1 지속, o2 PASS(해소), o3 결과에서 사라짐(해소 아님), o4 새 불일치, o5 UNVERIFIED ---
silver("S2", "2026-10-21 15:00:00", [("o1", "MISMATCH", 30000, 20000), ("o2", "PASS", 50000, 50000), ("o4", "MISMATCH", 7000, 6000), ("o5", "UNVERIFIED", 9000, None)])
regular_run(query, write, CFG, at(15, 7))
new = [x for x in r6("AND detected_at >= '2026-10-21 15:00:00'")]
check("두 번째 실행: 새 줄 2개 (새 불일치 o4 = OPEN, 해소 o2 = RESOLVED)", sorted((x["scope_key"], x["status"]) for x in new), [("orders", "OPEN"), ("orders-resolved", "RESOLVED")])
by = {x["scope_key"]: json.loads(x["evidence_ref"]) for x in new}
check("새 불일치는 o4만 (o1은 지속이라 다시 안 셈, o5는 보류)", by["orders"]["new_orders"], ["o4"])
check("해소는 o2만 (o3은 결과에서 사라졌을 뿐이라 해소 아님)", by["orders-resolved"]["resolved_orders"], ["o2"])
check("지금 열려 있는 주문: o1, o3, o4", sorted(open_orders([r["evidence_ref"] for r in r6()])), ["o1", "o3", "o4"])

# --- 세 번째 실행: o3 PASS -> 해소 ---
silver("S3", "2026-10-21 16:00:00", [("o1", "MISMATCH", 30000, 20000), ("o3", "PASS", 10000, 10000), ("o4", "MISMATCH", 7000, 6000)])
regular_run(query, write, CFG, at(16, 7))
last = r6("AND detected_at >= '2026-10-21 16:00:00'")
check("세 번째 실행: o3만 해소, 새 이상 없음", [(x["scope_key"], json.loads(x["evidence_ref"]).get("resolved_orders")) for x in last], [("orders-resolved", ["o3"])])
check("해소 뒤 열려 있는 주문: o1, o4", sorted(open_orders([r["evidence_ref"] for r in r6()])), ["o1", "o4"])

# --- 최신 실행만 읽는다, 다른 검사 이름은 무시 ---
silver("S0-old", "2026-10-21 10:00:00", [("o9", "MISMATCH", 1000, 500)])
silver("S4", "2026-10-21 17:00:00", [("o1", "MISMATCH", 30000, 20000), ("o4", "MISMATCH", 7000, 6000)], check="other_check")
n = len(r6())
regular_run(query, write, CFG, at(16, 52))
check("오래된 실행(o9)과 다른 검사 이름의 결과는 읽지 않음", len(r6()), n)

# --- 재판정(재처리 비교)에는 섞이지 않는다 ---
con.execute("INSERT INTO gold_b.reprocess_events (request_id, step, at, actor, window_start, window_end) VALUES ('rq-x', 'LEDGER_REPLACED', '2026-10-21 17:30:00', 'reprocess_job', '2026-10-21 14:00:00', '2026-10-21 15:00:00')")
s = run_once(query, write, CFG, at(17, 40))
check("R6 이상은 재판정 비교에서 빠짐 (이전 이상이 R6뿐이면 NO_ANOMALY_BEFORE)", [x["result"] for x in s["redetected"]], ["NO_ANOMALY_BEFORE"])
check("VERIFIED 내용에 제외한 규칙으로 R6이 적힘", R6_RULE in query("SELECT detail FROM gold_b.reprocess_events WHERE step = 'VERIFIED'")[0]["detail"], True)

# --- 입력 검사 ---
for bad in (Config(dialect="sqlite", silver_checks_table="silver.x; DROP TABLE y"), Config(dialect="sqlite", silver_checks_table=TABLE, r6_check_name="a' OR '1'='1")):
    try:
        regular_run(query, write, bad, at(18, 7))
        check("잘못된 표 이름·검사 이름은 거절", "통과됨", "오류")
    except ValueError:
        check("잘못된 표 이름·검사 이름은 거절", "오류", "오류")
# --- Silver 실행 목록 표를 쓰면: 완료된 실행만, 완료 시각 순서. 품질이 PASS가 아니면 해소하지 않는다 ---
con = build()
CFG2 = Config(dialect="sqlite", silver_checks_table=TABLE, silver_runs_table="silver.silver_runs", lag_sec=60.0, format_rule_version="v1.0")


def silver_run_row(run, completed, status, quality):
    con.execute("INSERT INTO silver.silver_runs VALUES (?,?,?,?)", (run, completed, status, quality))


silver("R-A", "2026-10-21 14:00:00", [("o1", "MISMATCH", 30000, 20000), ("o2", "MISMATCH", 50000, 40000)])
silver_run_row("R-A", "2026-10-21 14:05:00", "COMPLETED", "INCOMPLETE")
regular_run(query, write, CFG2, at(14, 12))
check("실행 목록 표: 완료된 실행의 불일치 2건이 이상으로 기록됨", [(x["scope_key"], x["observed_value"]) for x in r6()], [("orders", 2)])

silver("R-B", "2026-10-21 15:00:00", [("o1", "MISMATCH", 30000, 20000), ("o2", "PASS", 50000, 50000)])   # 검사는 있지만 아직 완료 표시가 없는 실행
silver_run_row("R-B", "2026-10-21 15:05:00", "RUNNING", None)
regular_run(query, write, CFG2, at(15, 12))
check("완료되지 않은 실행(RUNNING)은 읽지 않음", len(r6()), 1)

silver_run_row("R-B", "2026-10-21 15:06:00", "COMPLETED", "INCOMPLETE")
regular_run(query, write, CFG2, at(15, 27))
check("품질이 INCOMPLETE인 실행에서는 PASS 줄이 있어도 해소하지 않음", [x["scope_key"] for x in r6()], ["orders"])

con.execute("UPDATE silver.silver_runs SET quality_status = 'PASS' WHERE run_id = 'R-B'")
silver("R-B", "2026-10-21 15:00:00", [], check="order_item_total_match")
regular_run(query, write, CFG2, at(15, 32))
check("품질이 PASS인 실행에서는 PASS가 된 o2가 해소됨", sorted((x["scope_key"], json.loads(x["evidence_ref"]).get("resolved_orders")) for x in r6() if x["status"] == "RESOLVED"), [("orders-resolved", ["o2"])])


print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
