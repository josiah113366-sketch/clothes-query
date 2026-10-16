from collections import Counter
from ledger_v3 import generate_ledger, minute_of
from sample_data import INCIDENTS
import detect_v3 as D

EXPECT = {"PG_OUTAGE": {"R1"}, "INGEST_LAG": {"R3"}, "SCHEMA_POLLUTION": {"R4"}}
ALLOW = {"PG_OUTAGE": 20, "INGEST_LAG": 7, "SCHEMA_POLLUTION": 7}   # 분

def score(data, **kw):
    eps = D.episodes(D.run(*data, **kw)); hit, lat, used = {}, {}, set()
    for inc in INCIDENTS:
        s, e = minute_of(inc["start"]), minute_of(inc["end"]); al = ALLOW[inc["scenario"]]
        c = [x for x in eps if x[0] in EXPECT[inc["scenario"]] and x[3] >= s and x[2] <= e + al]
        hit[inc["incident_id"]] = bool(c)
        if c:
            used.update(c); lat[inc["incident_id"]] = min(x[2] for x in c) - s
    return hit, lat, [x for x in eps if x not in used]

def table(cfgs, seeds=range(30)):
    print(f"{'설정':<46}{'사건1':>6}{'사건2':>6}{'사건3':>6}{'오탐/일':>8}   걸린 시간(분) 사건1 평균/최대 | 사건2 | 사건3")
    for name, c in cfgs.items():
        H = Counter(); L = {k: [] for k in ("INC-001", "INC-002", "INC-003")}; fp = 0
        for s in seeds:
            data = generate_ledger(s, c["vol"]); h, l, f = score(data, **c.get("kw", {}))
            for k, v in h.items(): H[k] += v
            for k, v in l.items(): L[k].append(v)
            fp += len(f)
        a = lambda x: f"{sum(x)/len(x):.0f}" if x else "-"
        print(f"{name:<46}{H['INC-001']:>4}/30{H['INC-002']:>4}/30{H['INC-003']:>4}/30{fp/len(seeds):>8.2f}   "
              f"{a(L['INC-001'])}/{max(L['INC-001']) if L['INC-001'] else '-'} | {a(L['INC-002'])} | {a(L['INC-003'])}")

if __name__ == "__main__":
    cfg = {}
    for vol in (900, 3600):
        for k, w in ((2, 15), (3, 15), (3, 10), (4, 15)):
            cfg[f"R1: 최근 {w}분 PG원인 실패 >= {k}, {vol}주문/일"] = dict(vol=vol, kw=dict(r1_k=k, r1_win=w))
    table(cfg)
