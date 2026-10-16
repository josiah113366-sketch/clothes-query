"""탐지 규칙 v3: 원장을 1분마다 읽고 '최근 N분'을 묶어서 판정한다."""
import hashlib
from ledger_v3 import prefix, MIN
from sample_data import PGS, TOPICS, DAY
from datetime import timedelta

DEFAULT = dict(r1_win=15, r1_k=3, lag_sec=60, miss_min=3, r4_win=5, mal_min=5, mal_ratio=0.05, visible_delay=1, step=1)

def run(pay, msg, mal, lag, **kw):
    p = {**DEFAULT, **kw}
    d = p["visible_delay"]            # 원장에 보이기까지 1분 (1분마다 쌓음)
    fires = []                         # (분, rule, scope)
    pf = {pg: prefix(pay[pg]["pg_fail"]) for pg in PGS}
    mp = {t: prefix(msg[t]) for t in TOPICS}
    ml = {t: prefix(mal[t]) for t in TOPICS}
    for T in range(0, MIN, p["step"]):               # 탐지가 1분마다 돈다. T분 시점에는 T-d분까지의 원장이 보인다.
        v = T - d
        if v < 0: continue
        for pg in PGS:                 # R1: 최근 r1_win분 PG 원인 실패 합
            a = max(0, v - p["r1_win"] + 1)
            if pf[pg][v+1] - pf[pg][a] >= p["r1_k"]:
                fires.append((T, "R1", f"pg={pg}"))
        for t in TOPICS:
            cur = lag[t][v]            # R3: 최신 지연 스냅샷, 또는 스냅샷이 연속으로 없음
            if cur is not None and cur >= p["lag_sec"]:
                fires.append((T, "R3", f"topic={t}"))
            elif v >= p["miss_min"] - 1 and all(lag[t][x] is None for x in range(v - p["miss_min"] + 1, v + 1)):
                fires.append((T, "R3", f"topic={t}"))
            a = max(0, v - p["r4_win"] + 1)   # R4: 최근 r4_win분 형식 오류
            m, n = ml[t][v+1] - ml[t][a], mp[t][v+1] - mp[t][a]
            if n and m >= p["mal_min"] and m / n >= p["mal_ratio"]:
                fires.append((T, "R4", f"topic={t}"))
    return fires

def episodes(fires, gap=5):
    gap = max(gap, 0)
    from collections import defaultdict
    g = defaultdict(list)
    for T, r, s in fires: g[(r, s)].append(T)
    eps = []
    for (r, s), ts in g.items():
        ts.sort(); start = prev = ts[0]
        for t in ts[1:]:
            if t - prev > gap: eps.append((r, s, start, prev)); start = t
            prev = t
        eps.append((r, s, start, prev))
    return eps
