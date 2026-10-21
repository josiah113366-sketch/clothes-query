"""판정 잡 틀 시험. sqlite 가짜 원장으로 순찰 한 바퀴를 직접 돌려 본다 (Athena는 아직 안 돌려봤다).

실행: python3 test_job.py
"""
import sqlite3
from datetime import datetime, timedelta

from job import floor_tick, pending_replacements, regular_run, run_once
from rules import r3_bronze_lag
from rules import Config, anomaly_id

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


CFG = Config(dialect="sqlite", lag_sec=60.0, format_rule_version="v1.0")   # 시험 데이터에 맞춘 값 (실제 기본값은 아래에서 따로 시험)
F = "%Y-%m-%d %H:%M:%S"
D0 = datetime(2026, 10, 20, 14, 0)


def at(h, m=0):
    return datetime(2026, 10, 20, h, m)


def build():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ':memory:' AS gold_b")
    con.executescript("""
    CREATE TABLE gold_b.payment_attempts (payment_id, order_id, attempt_no, pg, status, failure_code, failure_cause, completed_at, loaded_at);
    CREATE TABLE gold_b.topic_messages (topic, kafka_partition, kafka_offset, kafka_timestamp, loaded_at);
    CREATE TABLE gold_b.bronze_lag_snapshots (collected_at, topic, "partition", end_offset, committed_offset, lag_msgs, lag_sec, connector_state);
    CREATE TABLE gold_b.malformed_messages (topic, kafka_partition, kafka_offset, rule_version, kafka_timestamp, error_count, reason, loaded_at);
    CREATE TABLE gold_b.reprocess_events (request_id, step, at, actor, reason, window_start, window_end, rule_version, source, attempt, parent_request_id, detail);
    CREATE TABLE gold_b.anomaly (run_id, anomaly_id, rule_id, rule_version, anomaly_type, source_table, window_start, window_end, scope_type, scope_key,
                                 metric, observed_value, baseline_value, baseline_kind, sample_size, episode_start, episode_end, evidence_ref, status, detected_at);
    CREATE TABLE gold_b.detection_runs (run_id, kind, request_id, judged_from, judged_to, started_at, anomaly_count);
    """)
    pay, msg, lag = [], [], []
    n = 0
    for k in range(180):                                   # 14:00 ~ 16:59, 1분마다
        t = D0 + timedelta(minutes=k)
        loaded = (t + timedelta(minutes=1)).strftime(F)
        outage = at(15, 0) <= t < at(15, 30)
        for pg in ("PG_A", "PG_B"):
            for i in range(3):
                n += 1
                fail = outage and pg == "PG_A"
                pay.append((f"p{n}", f"o{n}", 1, pg, "FAILED" if fail else "SUCCESS", "PG_TIMEOUT" if fail else None,
                            "PG" if fail else None, t.strftime(F), loaded))
        for topic in CFG.topics:
            for i in range(10):
                msg.append((topic, 0, k * 10 + i, t.strftime(F), loaded))
            slow = topic == "orders" and at(16, 20) <= t < at(16, 30)
            gone = topic == "payments" and at(16, 40) <= t < at(16, 50)
            if not gone:
                lag.append((t.strftime(F), topic, 0, 0, 0, 0, 200.0 if slow else 5.0, "RUNNING"))
    # 데이터 오염: 15:20에 끝난 PG_B 성공 주문 3건(o484~o486)에 성공 결제를 한 건씩 더 넣고, 적재는 16:41에 된 것처럼 한다.
    # 중복 행의 completed_at은 원래 결제 시각(+2초)이라 과거다. 정상 재시도(실패 뒤 성공)는 넣어도 이상이 아니어야 한다.
    for i, oid in enumerate(("o484", "o485", "o486")):
        pay.append((f"dup{i}", oid, 2, "PG_B", "SUCCESS", None, None, "2026-10-20 15:20:02", "2026-10-20 16:41:00"))
    pay.append(("rt0", "o-retry", 1, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-20 16:41:10", "2026-10-20 16:41:30"))
    pay.append(("rt1", "o-retry", 2, "PG_B", "SUCCESS", None, None, "2026-10-20 16:41:40", "2026-10-20 16:42:00"))
    con.executemany("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)", pay)
    con.executemany("INSERT INTO gold_b.topic_messages VALUES (?,?,?,?,?)", msg)
    con.executemany("INSERT INTO gold_b.bronze_lag_snapshots VALUES (?,?,?,?,?,?,?,?)", lag)
    bad = [("clickstream", 0, 7000 + i, "v1.0", at(16, 3 + i % 4).strftime(F), 1, "MISSING_FIELD", at(16, 8).strftime(F)) for i in range(10)]
    bad += [("orders", 0, 8000 + i, "v0.9", at(16, 3 + i % 4).strftime(F), 1, "MISSING_FIELD", at(16, 8).strftime(F)) for i in range(12)]   # 옛 규칙 버전
    con.executemany("INSERT INTO gold_b.malformed_messages VALUES (?,?,?,?,?,?,?,?)", bad)
    return con


con = build()


def query(sql):
    return [dict(r) for r in con.execute(sql).fetchall()]


def write(table, rows):
    for r in rows:
        cols = ",".join(r)
        con.execute(f"INSERT INTO gold_b.{table} ({cols}) VALUES ({','.join('?' * len(r))})", list(r.values()))


def anomalies(where=""):
    return query(f"SELECT * FROM gold_b.anomaly {where} ORDER BY run_id, anomaly_id")


# --- 순찰 번호 ---
check("5분 단위로 내린다", floor_tick(datetime(2026, 10, 20, 15, 12, 41)), datetime(2026, 10, 20, 15, 10))

# --- 장애 전에는 이상 없음 ---
r = regular_run(query, write, CFG, datetime(2026, 10, 20, 14, 30, 5))
check("14:30 순찰: 이상 없음, 순찰 기록은 남음", (r["anomalies"], len(query("SELECT * FROM gold_b.detection_runs"))), (0, 1))
check("같은 순찰 번호는 다시 안 돎", regular_run(query, write, CFG, datetime(2026, 10, 20, 14, 31, 0)).get("skipped"), True)

# --- 3분 대기: 장애가 막 시작한 직후에는 비율이 낮아 아직 안 잡힌다 ---
regular_run(query, write, CFG, at(15, 5))
check("15:05 순찰: 아직 안 잡힘 (최근 3분 데이터는 안 봄, 비율 13%)", len(anomalies("WHERE rule_id = 'R1_PG_FAILURES'")), 0)
regular_run(query, write, CFG, at(15, 10))
r1 = anomalies("WHERE rule_id = 'R1_PG_FAILURES'")
check("15:10 순찰: PG_A만 잡힘 (실패 21건, 비율 47%)", [(x["scope_key"], x["observed_value"], x["sample_size"]) for x in r1], [("PG_A", 21, 45)])
check("anomaly_id 규칙: 같은 입력이면 같은 id", r1[0]["anomaly_id"], anomaly_id("R1_PG_FAILURES", "v0.1", "PG_A", r1[0]["window_start"]))
check("회차 번호가 줄에 찍힘", r1[0]["run_id"], "20261020T1510Z")

# --- R3, R4 ---
regular_run(query, write, CFG, at(16, 25))
r3 = anomalies("WHERE rule_id = 'R3_BRONZE_LAG'")
check("16:25 순찰: orders 지연 200초가 잡힘, 유입은 평소대로(증거)", [(x["scope_key"], x["observed_value"], '"ingest_last_window": 50' in x["evidence_ref"]) for x in r3], [("orders", 200.0, True)])
regular_run(query, write, CFG, at(16, 45))
r3 = anomalies("WHERE rule_id = 'R3_BRONZE_LAG' AND run_id = '20261020T1645Z'")
check("16:45 순찰: payments 측정 줄이 없어서 잡힘", [(x["scope_key"], '"no_snapshots": true' in x["evidence_ref"]) for x in r3], [("payments", True)])
r5 = anomalies("WHERE rule_id = 'R5_DUPLICATE_SUCCESS'")
check("16:45 순찰까지: 중복 성공 결제는 16:45 순찰에서만 잡힘(주문 3개, 정상 재시도는 안 셈)", [(x["run_id"], x["scope_key"], x["observed_value"]) for x in r5], [("20261020T1645Z", "all", 3)])
check("R5 증거에 주문 id가 붙음", '"sample_order_ids": ["o484", "o485", "o486"]' in r5[0]["evidence_ref"], True)
regular_run(query, write, CFG, at(16, 50))
check("다음 순찰(16:50)에서는 같은 줄을 다시 세지 않음", len(anomalies("WHERE rule_id = 'R5_DUPLICATE_SUCCESS'")), 1)
regular_run(query, write, CFG, at(16, 10))
r4 = anomalies("WHERE rule_id = 'R4_MALFORMED'")
check("16:10 순찰: clickstream 깨진 메시지 10개만 (옛 규칙 v0.9의 orders 12개는 안 셈)", [(x["scope_key"], x["observed_value"]) for x in r4], [("clickstream", 10)])

# --- 재처리 뒤 재판정 ---
before = len(anomalies())
def event(rid, step, ws, we):
    write("reprocess_events", [{"request_id": rid, "step": step, "at": at(16, 15).strftime(F), "actor": "reprocess_job", "reason": None,
                                 "window_start": ws.strftime(F), "window_end": we.strftime(F), "rule_version": "v1.0", "source": "KAFKA",
                                 "attempt": 1, "parent_request_id": None, "detail": None}])
for tick_min in range(15, 60, 5):                          # 15시대를 정규 순찰로 먼저 훑어 이상 이력을 만들어 둔다
    regular_run(query, write, CFG, at(15, tick_min) + timedelta(minutes=15))
check("재처리 전에 PG_A 이상이 기록되어 있음", len(anomalies("WHERE rule_id = 'R1_PG_FAILURES'")) > 1, True)

event("rq-0", "LEDGER_REPLACED", at(15, 0), at(16, 0))     # 교체는 했는데 데이터는 그대로 (장애가 진짜였던 경우)
check("교체 끝났는데 아직 재판정 안 한 줄을 찾음", [(x["request_id"], x["window_start"]) for x in pending_replacements(query)], [("rq-0", "2026-10-20 15:00:00")])
s = run_once(query, write, CFG, at(16, 20))
check("재판정 결과: 장애가 진짜라 이상이 그대로 남음 (STILL_OPEN)", [x["result"] for x in s["redetected"]], ["STILL_OPEN"])
check("REDETECTED, VERIFIED 줄이 남음", [x["step"] for x in query("SELECT step FROM gold_b.reprocess_events WHERE actor = 'detect_job' AND request_id = 'rq-0' ORDER BY step")], ["REDETECTED", "VERIFIED"])
check("같은 교체를 두 번 재판정하지 않음", len(run_once(query, write, CFG, at(16, 25))["redetected"]), 0)

con.execute("UPDATE gold_b.payment_attempts SET status='SUCCESS', failure_code=NULL, failure_cause=NULL, loaded_at=? WHERE completed_at >= ? AND completed_at < ?",
            (at(16, 28).strftime(F), at(15, 0).strftime(F), at(16, 0).strftime(F)))   # 재처리로 원장이 바뀐 것을 흉내
con.execute("DELETE FROM gold_b.payment_attempts WHERE payment_id LIKE 'dup%'")   # 중복 성공 결제도 재처리 결과에서 없어졌다고 가정(실제로는 원본 DB에 남아 있으면 그대로 다시 나온다)
event("rq-1", "LEDGER_REPLACED", at(15, 0), at(16, 0))
s = run_once(query, write, CFG, at(16, 30))
check("재처리로 원장이 바뀐 뒤 재판정: 이상이 사라짐 (RESOLVED)", [x["result"] for x in s["redetected"]], ["RESOLVED"])
check("옛 이상 줄은 지워지지 않음 (쌓기만 함)", len(anomalies()) >= before, True)
check("재판정 순찰 기록 2건(REDETECT)", len(query("SELECT * FROM gold_b.detection_runs WHERE kind = 'REDETECT'")), 2)
check("VERIFIED 내용에 해결 결과가 들어감", '"result": "RESOLVED"' in query("SELECT detail FROM gold_b.reprocess_events WHERE request_id='rq-1' AND step='VERIFIED'")[0]["detail"], True)

# --- 은서 님 리뷰 반영 ---
def blank():
    """스키마만 있는 새 가짜 원장. (query, write, 연결)을 돌려준다."""
    c = build()
    for tb in ("payment_attempts", "topic_messages", "bronze_lag_snapshots", "malformed_messages", "reprocess_events", "anomaly", "detection_runs"):
        c.execute(f"DELETE FROM gold_b.{tb}")

    def q(sql):
        return [dict(r) for r in c.execute(sql).fetchall()]

    def w(table, rows):
        for r in rows:
            c.execute(f"INSERT INTO gold_b.{table} ({','.join(r)}) VALUES ({','.join('?' * len(r))})", list(r.values()))
    return q, w, c


def replaced(c, rid, ws, we, at_):
    c.execute("INSERT INTO gold_b.reprocess_events (request_id, step, at, actor, window_start, window_end) VALUES (?, 'LEDGER_REPLACED', ?, 'reprocess_job', ?, ?)",
              (rid, at_, ws, we))


# 1. 교체 구간 끝의 3분(15:57~16:00)에 끝난 결제도 재판정이 본다
q2, w2, c2 = blank()
for i in range(5):
    c2.execute("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)", (f"e{i}", f"oe{i}", 1, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-20 15:58:30", "2026-10-20 16:30:00"))
replaced(c2, "rq-a", "2026-10-20 15:00:00", "2026-10-20 16:00:00", "2026-10-20 16:30:00")
run_once(q2, w2, CFG, at(16, 40))
check("재판정이 교체 구간 끝 3분(15:58 결제)까지 봄", [(x["scope_key"], x["observed_value"]) for x in q2("SELECT * FROM gold_b.anomaly WHERE rule_id = 'R1_PG_FAILURES' ORDER BY anomaly_id")][:1], [("PG_A", 5)])

# 2. 재판정 비교에서 R3는 뺀다 (재처리가 bronze_lag_snapshots를 다시 만들지 않는다)
q2, w2, c2 = blank()
base = dict(run_id="old", rule_version="v0.1", source_table="x", window_start="2026-10-20 15:10:00", window_end="2026-10-20 15:20:00", scope_type="topic", scope_key="orders", status="OPEN", detected_at="2026-10-20 15:21:00")
w2("anomaly", [dict(base, anomaly_id="a-old-r3", rule_id="R3_BRONZE_LAG", anomaly_type="BRONZE_LAG_SPIKE"),
               dict(base, anomaly_id="a-old-r1", rule_id="R1_PG_FAILURES", anomaly_type="PG_FAILURE_SPIKE", scope_type="pg", scope_key="PG_A")])
replaced(c2, "rq-b", "2026-10-20 15:00:00", "2026-10-20 16:00:00", "2026-10-20 16:30:00")
s = run_once(q2, w2, CFG, at(16, 40))
check("R3 이상이 옛 기록에 있어도 R1이 사라졌으면 RESOLVED (R3는 비교 제외)", [x["result"] for x in s["redetected"]], ["RESOLVED"])
check("VERIFIED 내용에 제외한 규칙이 적힘", "R3_BRONZE_LAG" in q2("SELECT detail FROM gold_b.reprocess_events WHERE step = 'VERIFIED'")[0]["detail"], True)
check("재판정은 R3 이상 줄을 새로 만들지 않음", len(q2("SELECT * FROM gold_b.anomaly WHERE rule_id = 'R3_BRONZE_LAG' AND run_id LIKE '%-RD-%'")), 0)

# 3. 재처리로 교체된 줄(loaded_at이 교체 때)은 R5 순찰이 새로 적재된 것으로 보지 않는다. 교체 뒤 새로 들어온 중복은 센다
q2, w2, c2 = blank()
ins = "INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)"
c2.execute(ins, ("n9", "o9", 1, "PG_B", "SUCCESS", None, None, "2026-10-20 15:20:00", "2026-10-20 15:21:00"))
c2.execute(ins, ("d9", "o9", 2, "PG_B", "SUCCESS", None, None, "2026-10-20 15:20:02", "2026-10-20 17:02:00"))      # 재처리로 다시 적재된 중복 (교체 기록 17:03 이전)
c2.execute(ins, ("n10", "o10", 1, "PG_B", "SUCCESS", None, None, "2026-10-20 15:30:00", "2026-10-20 15:31:00"))
c2.execute(ins, ("d10", "o10", 2, "PG_B", "SUCCESS", None, None, "2026-10-20 15:30:02", "2026-10-20 17:04:00"))    # 교체 뒤 새로 들어온 중복
replaced(c2, "rq-c", "2026-10-20 15:00:00", "2026-10-20 16:00:00", "2026-10-20 17:03:00")
regular_run(q2, w2, CFG, at(17, 5))
r5 = q2("SELECT observed_value, evidence_ref FROM gold_b.anomaly WHERE rule_id = 'R5_DUPLICATE_SUCCESS'")
check("재처리 직후 순찰: 교체로 다시 적재된 중복(o9)은 안 세고, 교체 뒤 새 중복(o10)만 셈", (len(r5), r5[0]["observed_value"], '"sample_order_ids": ["o10"]' in r5[0]["evidence_ref"]), (1, 1, True))

# 4. 기본 설정값: 정상 톱니(900초)에서는 안 울리고, 실제 토픽 5개를 본다
d = Config()
check("기본 토픽은 실제 배포된 5개 (members-events 포함, reviews.raw 없음)", (len(d.topics), "members-events" in d.topics, "reviews.raw" in d.topics), (5, True, False))
snaps = {t: 1 for t in d.topics}
quiet = r3_bronze_lag(d, "r", at(16), (at(15, 55), at(16)), {"orders": 900.0}, snaps, {})
loud = r3_bronze_lag(d, "r", at(16), (at(15, 55), at(16)), {"orders": 1300.0}, snaps, {})
check("기본 R3: 정상 톱니 900초는 조용, 1300초는 울림", (len(quiet), len(loud)), (0, 1))

# 5. write()가 받는 시각은 모두 'YYYY-MM-DD HH:MM:SS' (UTC). 실제 write는 이것을 TIMESTAMP 타입으로 바꿔 써야 한다
bad = []
for tb, cols in (("anomaly", ("window_start", "window_end", "detected_at")), ("detection_runs", ("judged_from", "judged_to", "started_at")),
                 ("reprocess_events", ("at", "window_start", "window_end"))):
    for r in query(f"SELECT * FROM gold_b.{tb}"):
        for cname in cols:
            if r[cname] is not None:
                try:
                    datetime.strptime(str(r[cname]), F)
                except ValueError:
                    bad.append((tb, cname, r[cname]))
check("쓰는 줄의 시각 컬럼이 모두 'YYYY-MM-DD HH:MM:SS' 형식", bad, [])

# 6. 이상 줄을 쓰고 순찰 기록을 쓰기 전에 멈췄다가 같은 순찰을 다시 돌려도 이상 줄이 두 번 쌓이지 않는다
n_before = len(query("SELECT * FROM gold_b.anomaly WHERE run_id = '20261020T1510Z'"))
con.execute("DELETE FROM gold_b.detection_runs WHERE run_id = '20261020T1510Z'")
regular_run(query, write, CFG, datetime(2026, 10, 20, 15, 10, 20))
check("같은 순찰을 다시 돌려도 이상 줄이 늘지 않음", (n_before > 0, len(query("SELECT * FROM gold_b.anomaly WHERE run_id = '20261020T1510Z'"))), (True, n_before))

# --- 재영 님 리뷰: 저장 도중 실패한 작업을 다시 돌려도 이상 줄과 순찰 기록이 두 번 쌓이지 않는다 ---
class Boom(RuntimeError):
    pass


def flaky(write_fn, fail_on, times=1):
    """fail_on 표에 쓸 때 times번 실패하는 write."""
    left = {"n": times}

    def w(table, rows):
        if table == fail_on and left["n"] > 0:
            left["n"] -= 1
            raise Boom(table)
        write_fn(table, rows)
    return w


q3, w3, c3 = blank()
for i in range(6):
    c3.execute("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)", (f"f{i}", f"of{i}", 1, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-20 15:02:00", "2026-10-20 15:03:00"))
TICK = datetime(2026, 10, 20, 15, 10)
bad = flaky(w3, "detection_runs")
try:
    regular_run(q3, bad, CFG, datetime(2026, 10, 20, 15, 10, 30), TICK)
    check("순찰 기록을 쓰다 실패하면 오류가 올라옴", "통과됨", "오류")
except Boom:
    check("순찰 기록을 쓰다 실패하면 오류가 올라옴", "오류", "오류")
n1 = len(q3("SELECT * FROM gold_b.anomaly"))
res = regular_run(q3, bad, CFG, datetime(2026, 10, 20, 15, 23, 0), TICK)       # 몇 분 뒤 재시도 (같은 순찰 시각 TICK을 받음)
check("재시도해도 이상 줄이 두 번 쌓이지 않음 (같은 순찰 번호)", (n1 > 0, len(q3("SELECT * FROM gold_b.anomaly")), res["run_id"]), (True, n1, "20261020T1510Z"))
check("재시도에서 순찰 기록이 한 줄 쓰이고, 이상 개수는 처음 판정한 개수 그대로", [(x["run_id"], x["anomaly_count"]) for x in q3("SELECT * FROM gold_b.detection_runs")], [("20261020T1510Z", n1)])
check("그다음 재실행은 건너뜀", regular_run(q3, bad, CFG, datetime(2026, 10, 20, 15, 24, 0), TICK).get("skipped"), True)

# 재판정: 이상과 순찰 기록을 쓴 뒤 재처리 기록(REDETECTED/VERIFIED) 쓰기가 실패해도, 재시도가 이중 저장하거나 STILL_OPEN으로 잘못 판정하지 않는다
q4, w4, c4 = blank()
for i in range(6):
    c4.execute("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)", (f"g{i}", f"og{i}", 1, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-20 15:20:00", "2026-10-20 16:30:00"))
replaced(c4, "rq-r", "2026-10-20 15:00:00", "2026-10-20 16:00:00", "2026-10-20 16:30:00")
bad2 = flaky(w4, "reprocess_events")
try:
    run_once(q4, bad2, CFG, datetime(2026, 10, 20, 16, 40), None)
    check("재처리 기록을 쓰다 실패하면 오류가 올라옴", "통과됨", "오류")
except Boom:
    check("재처리 기록을 쓰다 실패하면 오류가 올라옴", "오류", "오류")
rd1 = len(q4("SELECT * FROM gold_b.anomaly WHERE run_id LIKE '%-RD-%'"))
s2 = run_once(q4, bad2, CFG, datetime(2026, 10, 20, 17, 5), None)                 # 한 시간 가까이 뒤에 재시도 (순찰 시각이 달라도)
check("재판정 재시도: 이상 줄이 두 번 쌓이지 않음", (rd1 > 0, len(q4("SELECT * FROM gold_b.anomaly WHERE run_id LIKE '%-RD-%'"))), (True, rd1))
check("재판정 재시도: 순찰 기록 REDETECT가 한 줄만", len(q4("SELECT * FROM gold_b.detection_runs WHERE kind = 'REDETECT'")), 1)
check("재판정 재시도: 이전 시도가 쓴 이상 줄을 옛 이상으로 착각하지 않음 (옛 이상이 없었으니 NO_ANOMALY_BEFORE)", [x["result"] for x in s2["redetected"]], ["NO_ANOMALY_BEFORE"])
check("재판정 재시도: VERIFIED가 한 줄만", len(q4("SELECT * FROM gold_b.reprocess_events WHERE step = 'VERIFIED'")), 1)
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
