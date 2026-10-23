"""진짜 모델 시험대: 가짜 장부(sqlite)와 진짜 모델(Bedrock)로 조사 루프를 돌려 보고, 모델이 원인 층을 맞히는지 본다.

Athena와 AWS 역할이 없어도 된다. 내 컴퓨터에서 Bedrock API 키(AWS_BEARER_TOKEN_BEDROCK)와 모델 ID(BEDROCK_MODEL_ID)만 있으면 돈다.
장부는 사건 3개(PG 장애, 소비 지연, 한 주문에 성공 결제 2건)와 정상 장부를 시간 순서대로 만든 가짜 데이터다. 정답 층은 사건에 정해져 있고,
모델에게는 이상 정보(정답 제외)와 조회 도구만 준다. 모델마다 같은 질문으로 비교하려고 만들었다.

사용 예 (PowerShell)
  $env:AWS_BEARER_TOKEN_BEDROCK = "<Bedrock API 키>"
  $env:BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"
  python try_model.py --scenario all --repeat 3

출력: 시나리오마다 원인 층(정답과 같은지), 걸린 시간, 모델 호출 수, 도구 호출 수, 되돌림 수, 토큰 수. 쿼리 내용은 출력하지 않는다.
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

from bedrock_io import BedrockConverse
from loop import investigate

F = "%Y-%m-%d %H:%M:%S"
T0 = datetime(2026, 10, 21, 15, 0, 0)
NOW = datetime(2026, 10, 21, 15, 31, 0)
TOPICS = ("payments", "orders", "order-items", "members-events", "clickstream")


def build(scenario):
    """사건 하나를 심은 가짜 장부. scenario: pg | lag | dup | clean (기본) / falsealarm | nodata | mixed (어려운 것)"""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ':memory:' AS gold_b")
    con.executescript("""
    CREATE TABLE gold_b.payment_attempts (payment_id, order_id, attempt_no, pg, status, failure_code, failure_cause, completed_at, loaded_at);
    CREATE TABLE gold_b.payment_events (payment_id, completed_at);
    CREATE TABLE gold_b.topic_messages (topic, kafka_partition, kafka_offset, kafka_timestamp, loaded_at);
    CREATE TABLE gold_b.bronze_lag_snapshots (collected_at, topic, "partition", end_offset, committed_offset, lag_msgs, lag_sec, connector_state);
    CREATE TABLE gold_b.malformed_events (topic, kafka_partition, kafka_offset, kafka_timestamp, field, reason, raw_sample, rule_version, loaded_at);
    CREATE TABLE gold_b.malformed_messages (topic, kafka_partition, kafka_offset, rule_version, kafka_timestamp, error_count, errors, loaded_at);
    CREATE TABLE gold_b.reprocess_events (request_id, step, at, actor, reason, window_start, window_end, rule_version, source, attempt, parent_request_id, detail);
    CREATE TABLE gold_b.anomaly (run_id, anomaly_id, rule_id, rule_version, anomaly_type, source_table, window_start, window_end, scope_type, scope_key,
                                 metric, observed_value, baseline_value, baseline_kind, sample_size, episode_start, episode_end, evidence_ref, status, detected_at);
    """)
    n, offsets = 0, {}
    for k in range(60):
        t = T0 + timedelta(minutes=k)
        stamp, loaded = t.strftime(F), (t + timedelta(minutes=1)).strftime(F)
        surge = scenario == "lag" and 10 <= k < 25
        pg_trouble = scenario in ("pg", "mixed")
        for pg in ("PG_A", "PG_B"):
            for i in range(3):
                n += 1
                bad = pg_trouble and pg == "PG_A" and 10 <= k < 25 and i < 3
                declined = scenario == "falsealarm" and pg == "PG_A" and 10 <= k < 25 and i < 3   # 같은 구간에 실패가 늘었지만 전부 고객 원인
                fail = bad or declined or (n % 90 == 0)            # 평소에도 가끔(1% 안팎) 고객 원인 실패가 섞인다
                cause = "PG" if bad else ("CUSTOMER" if fail else None)
                code = "PG_TIMEOUT" if bad else ("CARD_DECLINED" if fail else None)
                con.execute("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)", (f"p{n}", f"o{n}", 1, pg, "FAILED" if fail else "SUCCESS", code, cause, stamp, loaded))
                con.execute("INSERT INTO gold_b.payment_events VALUES (?,?)", (f"p{n}", stamp))
        for topic in TOPICS:
            for i in range(50 if surge else 10):
                off = offsets.get(topic, 0)
                offsets[topic] = off + 1
                con.execute("INSERT INTO gold_b.topic_messages VALUES (?,?,?,?,?)", (topic, off % 3, off // 3, stamp, loaded))
            lag = (300 + (k - 10) * 80) if surge and topic in ("orders", "order-items") else 40
            if scenario != "nodata":                 # nodata: 지연 측정 줄이 아예 없다(수집기가 안 돈다)
                con.execute("INSERT INTO gold_b.bronze_lag_snapshots VALUES (?,?,?,?,?,?,?,?)", (stamp, topic, 0, 1000, 900, 100, float(lag), "RUNNING"))
    if scenario in ("dup", "mixed"):
        for i in range(3):
            con.execute("INSERT INTO gold_b.payment_attempts VALUES (?,?,?,?,?,?,?,?,?)",
                        (f"dup{i}", f"o{20 + i}", 2, "PG_B", "SUCCESS", None, None, (T0 + timedelta(minutes=20)).strftime(F),
                         (T0 + timedelta(minutes=21 if scenario == "mixed" else 27)).strftime(F)))   # mixed는 PG 이상의 시간대(15:08~15:23) 안에 적재돼 도구가 중복을 보게 한다
    return con


BASIC = ("pg", "lag", "dup")
HARD = ("falsealarm", "nodata", "mixed")   # 정답은 이 시험대 만든 사람의 판단이다(팀 합의 값이 아님)
MUST_MENTION = {"mixed": "중복"}   # 이 시나리오에서는 결론이나 주장이 이 낱말(성공 결제 중복)을 언급해야 한다 (낱말 검사라 대략적이다)
SCENARIOS = {
    "pg": ("PAYMENT", {"anomaly_id": "a-demo-pg", "rule_id": "R1_PG_FAILURES", "anomaly_type": "PG_FAILURE_SPIKE", "source_table": "payment_attempts",
                       "window_start": "2026-10-21 15:08:00", "window_end": "2026-10-21 15:23:00", "scope_type": "pg", "scope_key": "PG_A",
                       "metric": "pg_cause_failures", "observed_value": 18, "baseline_value": 3, "evidence_ref": "{}"}),
    "lag": ("INGEST", {"anomaly_id": "a-demo-lag", "rule_id": "R3_BRONZE_LAG", "anomaly_type": "BRONZE_LAG_SPIKE", "source_table": "bronze_lag_snapshots",
                       "window_start": "2026-10-21 15:20:00", "window_end": "2026-10-21 15:25:00", "scope_type": "topic", "scope_key": "orders",
                       "metric": "bronze_lag_sec", "observed_value": 1380, "baseline_value": 1200, "evidence_ref": "{}"}),
    "dup": ("DATA_QUALITY", {"anomaly_id": "a-demo-dup", "rule_id": "R5_DUPLICATE_SUCCESS", "anomaly_type": "DUPLICATE_SUCCESS_PAYMENT", "source_table": "payment_attempts",
                             "window_start": "2026-10-21 15:25:00", "window_end": "2026-10-21 15:30:00", "scope_type": "global", "scope_key": "all",
                             "metric": "duplicate_success_orders", "observed_value": 3, "baseline_value": 0, "evidence_ref": "{}"}),
    # 이상 알림은 울렸지만 실패가 전부 고객 원인 → 결제(PG) 장애라고 할 증거가 없다. 억지로 층을 고르지 않고 UNKNOWN이 정답
    "falsealarm": ("UNKNOWN", {"anomaly_id": "a-demo-fa", "rule_id": "R1_PG_FAILURES", "anomaly_type": "PG_FAILURE_SPIKE", "source_table": "payment_attempts",
                               "window_start": "2026-10-21 15:08:00", "window_end": "2026-10-21 15:23:00", "scope_type": "pg", "scope_key": "PG_A",
                               "metric": "pg_cause_failures", "observed_value": 18, "baseline_value": 3, "evidence_ref": "{}"}),
    # 지연 알림인데 지연 측정 자체가 비어 있다 → 원장을 믿을 수 없어 판단 불가가 정답
    "nodata": ("UNKNOWN", {"anomaly_id": "a-demo-nd", "rule_id": "R3_BRONZE_LAG", "anomaly_type": "BRONZE_LAG_SPIKE", "source_table": "bronze_lag_snapshots",
                           "window_start": "2026-10-21 15:20:00", "window_end": "2026-10-21 15:25:00", "scope_type": "topic", "scope_key": "orders",
                           "metric": "bronze_lag_sec", "observed_value": 1380, "baseline_value": 1200, "evidence_ref": "{}"}),
    # PG 장애가 진짜이고 같은 시간대에 성공 결제 중복도 섞여 있다 → 이 이상(PG 장애)의 층은 PAYMENT
    "mixed": ("PAYMENT", {"anomaly_id": "a-demo-mx", "rule_id": "R1_PG_FAILURES", "anomaly_type": "PG_FAILURE_SPIKE", "source_table": "payment_attempts",
                          "window_start": "2026-10-21 15:08:00", "window_end": "2026-10-21 15:23:00", "scope_type": "pg", "scope_key": "PG_A",
                          "metric": "pg_cause_failures", "observed_value": 18, "baseline_value": 3, "evidence_ref": "{}"}),
}


def run(scenario, converse):
    expected, anomaly = SCENARIOS[scenario]
    con = build(scenario)
    start, before = time.time(), dict(converse.usage)
    report = investigate(anomaly, converse, lambda sql: [dict(r) for r in con.execute(sql).fetchall()], dialect="sqlite", now=NOW)
    trace = report["trace"]
    return {"scenario": scenario, "expected": expected, "said": report["cause_layer"], "match": report["cause_layer"] == expected,
            "seconds": round(time.time() - start, 1), "model_calls": converse.usage["calls"] - before["calls"],
            "tool_calls": sum(1 for t in trace if t["status"] == "ok"), "tool_errors": sum(1 for t in trace if t["status"] == "error"),
            "rejected": sum(1 for t in trace if t["status"] == "rejected"), "problems": len(report.get("problems", [])),
            "facts": sum(1 for c in report["claims"] if c.get("kind") == "FACT"), "assumptions": sum(1 for c in report["claims"] if c.get("kind") == "ASSUMPTION"),
            "conclusion": report["conclusion"], "claims": report["claims"],
            "mentions": None if scenario not in MUST_MENTION else MUST_MENTION[scenario] in (report["conclusion"] + " ".join(str(c.get("text")) for c in report["claims"]))}


def main(argv=None, env=None, converse=None):
    p = argparse.ArgumentParser(description="진짜 모델로 조사 루프를 가짜 장부에 돌려 본다.")
    p.add_argument("--scenario", default="all", choices=["all", "basic", "hard", *SCENARIOS],
                   help="basic=pg·lag·dup, hard=falsealarm·nodata·mixed, all=여섯 개 전부")
    p.add_argument("--show", action="store_true", help="모델이 쓴 결론과 주장(사실/추정)을 같이 출력해 품질을 눈으로 본다")
    p.add_argument("--repeat", type=int, default=1, help="같은 질문을 몇 번 돌릴지 (모델 답이 매번 조금 달라서 3번 이상 권장)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    converse = converse or BedrockConverse.from_env(env)
    names = {"all": list(SCENARIOS), "basic": list(BASIC), "hard": list(HARD)}.get(a.scenario, [a.scenario])
    results = []
    for name in names:
        for i in range(a.repeat):
            r = run(name, converse)
            results.append(r)
            print(f"{name} #{i + 1}: 정답 {r['expected']} / 모델 {r['said']} ({'맞음' if r['match'] else '다름'}), {r['seconds']}초, 모델 {r['model_calls']}번, "
                  f"도구 {r['tool_calls']}번(오류 {r['tool_errors']}), 되돌림 {r['rejected']}번, 사실 {r['facts']} 추정 {r['assumptions']}"
                  + (f", 검사를 못 넘긴 점 {r['problems']}개" if r["problems"] else "")
                  + ("" if r["mentions"] is None else f", 중복 결제 언급 {'있음' if r['mentions'] else '없음'}"))
            if a.show:
                print(f"    결론: {r['conclusion']}")
                for c in r["claims"]:
                    print(f"    - [{c.get('kind')}] {c.get('text')} (근거 {', '.join(e.get('tool', '?') for e in c.get('evidence', [])) or '없음'})")
    right = sum(r["match"] for r in results)
    print(f"모델 {converse.model_id}: 원인 층 {right}/{len(results)}개 맞힘, 토큰 입력 {converse.usage['input_tokens']} 출력 {converse.usage['output_tokens']}")
    return results


if __name__ == "__main__":
    main()
