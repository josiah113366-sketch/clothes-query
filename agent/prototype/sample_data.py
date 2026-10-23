"""가짜 Gold B 표 만들기 (은서 님 「Gold B 칼럼 구성」 컬럼 이름 기준).
표 2개(결제 지표, 파이프라인 지표)에 사건 3개를 심고, 정답표(incident_log)를 함께 돌려준다."""
import math, random
from datetime import datetime, timedelta

DAY = datetime(2026, 10, 20)
WIN = timedelta(minutes=5)
N_WIN = 288
PGS = ["PG_A", "PG_B"]
TOPICS = ["payments", "orders", "order-items", "member-events", "clickstream", "reviews.raw"]

def poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l:
            return k - 1

def at(h, m=0):
    return DAY + timedelta(hours=h, minutes=m)

# 정답표: 시뮬레이터가 주입한 사건 (UTC)
INCIDENTS = [
    dict(incident_id="INC-001", scenario="PG_OUTAGE", start=at(15), end=at(15, 30), scope_key="pg=PG_A", expected_layer="PAYMENT"),
    dict(incident_id="INC-002", scenario="INGEST_LAG", start=at(3), end=at(3, 30), scope_key="topic=*", expected_layer="INGEST"),
    dict(incident_id="INC-003", scenario="SCHEMA_POLLUTION", start=at(8), end=at(8, 30), scope_key="topic=clickstream", expected_layer="DATA_QUALITY"),
]

def active(inc_id, t):
    for i in INCIDENTS:
        if i["incident_id"] == inc_id and i["start"] <= t < i["end"]:
            return True
    return False

def generate(seed, orders_per_day=900):
    rng = random.Random(seed)
    lam_order = orders_per_day / N_WIN
    pay, pipe = [], []
    for w in range(N_WIN):
        ws = DAY + w * WIN
        we = ws + WIN
        surge = 20 if active("INC-002", ws) else 1
        pg_out = active("INC-001", ws)
        # --- 결제 지표 ---
        attempts_total = poisson(rng, lam_order * 1.15 * surge)
        counts = {pg: 0 for pg in PGS}
        for _ in range(attempts_total):
            counts[rng.choice(PGS)] += 1
        retry_extra = 0
        for pg in PGS:
            a = counts[pg]
            p_fail_pg = 0.9 if (pg_out and pg == "PG_A") else 0.0
            f_pg = sum(1 for _ in range(a) if rng.random() < p_fail_pg)
            f_cust = sum(1 for _ in range(a - f_pg) if rng.random() < 0.04)
            f = f_pg + f_cust
            retry = poisson(rng, 0.1 * a + (0.5 * f_pg if pg == "PG_B" else 0))
            pay.append(dict(window_start=ws, window_end=we, pg=pg, attempts=a, failures=f,
                            failure_rate=(f / a if a else None), pg_cause_failures=f_pg,
                            customer_cause_failures=f_cust, unknown_cause_failures=0, retry_attempts=retry))
        # --- 파이프라인 지표 ---
        base = {"payments": lam_order * 1.15, "orders": lam_order, "order-items": lam_order * 3.47,
                "member-events": 1500 / N_WIN, "clickstream": lam_order * 20, "reviews.raw": 1.0}
        for t in TOPICS:
            n = poisson(rng, base[t] * surge)
            lag_max = rng.uniform(4, 15)
            lag_avg = lag_max * 0.5
            if surge > 1:
                lag_max = rng.uniform(120, 420)
                lag_avg = lag_max * 0.4
            if rng.random() < (0.5 if surge > 1 else 0.03):
                lag_max = lag_avg = None  # Bronze 상태 보고가 아직 없음(NULL)
            mal, top = 0, None
            if t == "clickstream" and active("INC-003", ws):
                mal = int(n * rng.uniform(0.12, 0.2))
                top = "MISSING_FIELD"
            pipe.append(dict(window_start=ws, window_end=we, topic=t, kafka_msg_count=n,
                             bronze_row_count=(None if lag_max is None else n), bronze_lag_max_sec=lag_max, bronze_lag_avg_sec=lag_avg,
                             malformed_count=mal, malformed_top_reason=top, input_status="OK"))
    return pay, pipe, INCIDENTS
