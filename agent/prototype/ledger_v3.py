"""v3: 은서 님 '원장' 방식 기준 프로토타입 (2026-10-16).
Gold B가 1분마다 쌓는 원장(payment_attempts, topic_messages, bronze_lag_snapshots)을 흉내 낸다.
탐지는 1분마다 돌며, 원장에서 '최근 N분'을 직접 묶어서 센다. 구간 확정을 기다리지 않는다."""
import math, random
from sample_data import poisson, INCIDENTS, TOPICS, PGS

MIN = 1440  # 하루 1분 단위 칸 수
def minute_of(dt):
    return dt.hour * 60 + dt.minute

def active_min(inc_id, m):
    for i in INCIDENTS:
        if i["incident_id"] == inc_id and minute_of(i["start"]) <= m < minute_of(i["end"]):
            return True
    return False

def generate_ledger(seed, orders_per_day=900):
    """분 단위로 합친 원장: 한 칸 = 그 1분 동안 원장에 쌓인 행 수.
    (원장은 한 건씩 쌓이지만 탐지는 최근 N분을 세기만 하므로 분 단위 합계로 같은 결과를 낸다.)"""
    rng = random.Random(seed)
    lam = orders_per_day / MIN
    pay = {pg: dict(attempts=[0]*MIN, pg_fail=[0]*MIN, cust_fail=[0]*MIN) for pg in PGS}
    msg = {t: [0]*MIN for t in TOPICS}
    mal = {t: [0]*MIN for t in TOPICS}
    lag = {t: [None]*MIN for t in TOPICS}   # bronze_lag_snapshots: None = 그 분의 스냅샷이 없음
    base = {"payments": lam*1.15, "orders": lam, "order-items": lam*3.47, "member-events": 1500/MIN,
            "clickstream": lam*20, "reviews.raw": 1/5}
    for m in range(MIN):
        surge = 20 if active_min("INC-002", m) else 1
        out = active_min("INC-001", m)
        a_tot = poisson(rng, lam*1.15*surge)
        for _ in range(a_tot):
            pg = rng.choice(PGS)
            pay[pg]["attempts"][m] += 1
            if out and pg == "PG_A" and rng.random() < 0.9:
                pay[pg]["pg_fail"][m] += 1
            elif rng.random() < 0.04:
                pay[pg]["cust_fail"][m] += 1
        for t in TOPICS:
            n = poisson(rng, base[t]*surge)
            msg[t][m] = n
            if t == "clickstream" and active_min("INC-003", m):
                mal[t][m] = int(n*rng.uniform(0.12, 0.2))
            if rng.random() >= (0.5 if surge > 1 else 0.03):   # 스냅샷 누락(폭주 때 50%, 평소 3%)
                lag[t][m] = rng.uniform(120, 420) if surge > 1 else rng.uniform(4, 15)
    return pay, msg, mal, lag

def prefix(a):
    p = [0]
    for x in a: p.append(p[-1]+x)
    return p
