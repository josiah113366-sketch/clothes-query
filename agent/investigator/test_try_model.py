"""진짜 모델 시험대(try_model.py)의 가짜 장부가 조사 도구에서 사건대로 보이는지, 시험대가 모델 없이도 한 바퀴 도는지 확인한다.

실행: python3 test_try_model.py
"""
from datetime import datetime

import try_model
from loop import investigate
from try_model import BASIC, HARD, SCENARIOS, build, main

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


def q(con, sql):
    return [dict(r) for r in con.execute(sql).fetchall()]


con = build("pg")
a = q(con, "SELECT pg, COUNT(*) n, SUM(CASE WHEN failure_cause='PG' THEN 1 ELSE 0 END) pgf FROM gold_b.payment_attempts WHERE completed_at >= '2026-10-21 15:10:00' AND completed_at < '2026-10-21 15:25:00' GROUP BY pg ORDER BY pg")
check("PG 장애 장부: 15:10~15:25에 PG_A만 PG 원인 실패 45건 (15분 x 3건), PG_B는 0", [(r["pg"], r["pgf"]) for r in a], [("PG_A", 45), ("PG_B", 0)])
clean = q(build("clean"), "SELECT SUM(CASE WHEN failure_cause='PG' THEN 1 ELSE 0 END) pgf FROM gold_b.payment_attempts")[0]["pgf"]
check("정상 장부: PG 원인 실패 0", clean, 0)
lag = q(build("lag"), "SELECT MAX(lag_sec) m FROM gold_b.bronze_lag_snapshots WHERE topic='orders'")[0]["m"]
base = q(build("clean"), "SELECT MAX(lag_sec) m FROM gold_b.bronze_lag_snapshots WHERE topic='orders'")[0]["m"]
check("소비 지연 장부: orders 지연이 1000초를 넘고, 정상 장부는 40초", (lag > 1000, base), (True, 40.0))
vol = q(build("lag"), "SELECT COUNT(*) n FROM gold_b.topic_messages WHERE topic='orders' AND kafka_timestamp >= '2026-10-21 15:10:00' AND kafka_timestamp < '2026-10-21 15:25:00'")[0]["n"]
vol0 = q(build("clean"), "SELECT COUNT(*) n FROM gold_b.topic_messages WHERE topic='orders' AND kafka_timestamp >= '2026-10-21 15:10:00' AND kafka_timestamp < '2026-10-21 15:25:00'")[0]["n"]
check("소비 지연 장부: 구간 안 유입량이 정상의 5배", (vol0, vol), (150, 750))
dup = q(build("dup"), "SELECT order_id, COUNT(*) n FROM gold_b.payment_attempts WHERE status='SUCCESS' GROUP BY order_id HAVING COUNT(*) > 1 ORDER BY order_id")
check("성공 결제 중복 장부: 주문 3개가 성공 2건", [(r["order_id"], r["n"]) for r in dup], [("o20", 2), ("o21", 2), ("o22", 2)])

# 도구가 이 장부를 읽는지 (가짜 모델이 도구를 부르고 리포트를 냄)
class Scripted:
    model_id = "fake"
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def __init__(self):
        self.turns = [[{"toolUse": {"toolUseId": "1", "name": "payment_summary", "input": {"window_start": "2026-10-21T15:10:00", "window_end": "2026-10-21T15:25:00"}}}],
                      [{"toolUse": {"toolUseId": "2", "name": "submit_report", "input": {"cause_layer": "PAYMENT", "conclusion": "PG_A 장애",
                        "claims": [{"text": "PG_A 실패", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]}]}}}]]

    def __call__(self, system, messages, tool_specs):
        self.usage["calls"] += 1
        self.last = messages
        return {"role": "assistant", "content": self.turns.pop(0)}


m = Scripted()
r = try_model.run("pg", m)
res = str(m.last)
check("시험대: 도구가 가짜 장부를 읽어 PG_A의 PG 원인 실패를 모델에 돌려줌", ("PG_A" in res, "'pg_cause_failures': 45" in res), (True, True))
check("시험대: 모델이 PAYMENT를 말하면 맞음으로 셈", (r["match"], r["expected"], r["tool_calls"]), (True, "PAYMENT", 1))
check("모델에 넘기는 이상 정보에 정답(expected)이 없음", "expected" in str(SCENARIOS["pg"][1]), False)
check("시나리오 6개의 정답 층(기본 3 + 어려운 3)", {k: v[0] for k, v in SCENARIOS.items()},
      {"pg": "PAYMENT", "lag": "INGEST", "dup": "DATA_QUALITY", "falsealarm": "UNKNOWN", "nodata": "UNKNOWN", "mixed": "PAYMENT"})
check("기본·어려운 묶음", (BASIC, HARD), (("pg", "lag", "dup"), ("falsealarm", "nodata", "mixed")))
fa = q(build("falsealarm"), "SELECT SUM(CASE WHEN failure_cause='PG' THEN 1 ELSE 0 END) pgf, SUM(CASE WHEN pg='PG_A' AND failure_cause='CUSTOMER' AND completed_at >= '2026-10-21 15:10:00' AND completed_at < '2026-10-21 15:25:00' THEN 1 ELSE 0 END) cf FROM gold_b.payment_attempts")[0]
check("오탐 장부: PG 원인 실패 0, 같은 구간 PG_A 고객 원인 실패 45건 이상", (fa["pgf"], fa["cf"] >= 45), (0, True))
nd = q(build("nodata"), "SELECT COUNT(*) n FROM gold_b.bronze_lag_snapshots")[0]["n"]
check("자료 없음 장부: 지연 측정 줄이 0개", nd, 0)
mx = build("mixed")
check("혼합 장부: PG 장애와 성공 결제 중복이 함께 있음", (q(mx, "SELECT COUNT(*) n FROM gold_b.payment_attempts WHERE failure_cause='PG'")[0]["n"] > 0,
      len(q(mx, "SELECT order_id FROM gold_b.payment_attempts WHERE status='SUCCESS' GROUP BY order_id HAVING COUNT(*) > 1"))), (True, 3))
for name in HARD:
    check(f"어려운 시나리오 {name}: 모델에 넘기는 정보에 정답이 없음", "expected" in str(SCENARIOS[name][1]), False)

# --show 와 묶음 선택이 모델 없이 도는지
class Quick(Scripted):
    def __init__(self):
        super().__init__()
        self.turns = [[{"toolUse": {"toolUseId": "1", "name": "payment_summary", "input": {"window_start": "2026-10-21T15:10:00", "window_end": "2026-10-21T15:25:00"}}}],
                      [{"toolUse": {"toolUseId": "2", "name": "submit_report", "input": {"cause_layer": "UNKNOWN", "conclusion": "PG 원인 실패 없음",
                        "claims": [{"text": "PG 원인 실패 0건", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]}]}}}]]


import contextlib
import io
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res = main(["--scenario", "falsealarm", "--show"], env={}, converse=Quick())
out = buf.getvalue()
check("--show: 정답 UNKNOWN과 같게 맞힘, 결론과 주장(사실)·근거가 출력됨", (res[0]["match"], "결론: PG 원인 실패 없음" in out, "[FACT] PG 원인 실패 0건 (근거 payment_summary)" in out), (True, True, True))
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
