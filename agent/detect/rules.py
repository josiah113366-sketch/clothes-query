"""탐지 규칙 (순수 함수). 숫자만 받아서 이상 줄(anomaly)을 돌려준다. DB도 시계도 모른다.

규칙의 근거와 시험은 agent/prototype 의 프로토타입을 따른다. 임계값은 모두 임시값이다.
"""
import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    rule_version: str = "v0.1"            # 이 규칙 묶음의 버전. 규칙을 바꾸면 올린다 (anomaly_id에 들어간다)
    r1_win_min: int = 15                  # R1: 최근 몇 분의 PG 원인 실패를 보나
    r1_k: int = 3                         # R1: PG 원인 실패가 몇 건 이상
    r1_rate: float = 0.2                  # R1: 그 PG 결제 시도 중 PG 원인 실패 비율이 얼마 이상 (제안, 시험으로 고른 값)
    lag_sec: float = 60.0                 # R3: 적재 지연이 몇 초 이상
    miss_min: int = 3                     # R3: 측정 줄이 연속으로 몇 분 없으면 (미정)
    r4_win_min: int = 5                   # R4: 최근 몇 분의 깨진 메시지를 보나
    r4_min: int = 5                       # R4: 깨진 메시지가 몇 개 이상
    r4_ratio: float = 0.05                # R4: 그 토픽 메시지 중 깨진 비율이 얼마 이상
    ratio_wait_min: int = 3               # 비율 규칙은 구간이 끝난 지 몇 분 지난 것만 본다 (Gold B 문서)
    format_rule_version: str = "v1.0"     # 깨진 메시지를 셀 때 쓰는 형식 검사 규칙 버전 (현재 버전만 센다)
    pgs: tuple = ("PG_A", "PG_B")
    topics: tuple = ("payments", "orders", "order-items", "member-events", "clickstream", "reviews.raw")
    dialect: str = "athena"               # athena | sqlite (시각 표기만 다르다)


def anomaly_id(rule_id, rule_version, scope_key, window_start):
    """같은 규칙 버전·같은 대상·같은 시간대면 같은 id. 규칙 버전이 들어 있어 규칙을 바꿔도 옛 판정이 남는다."""
    raw = f"{rule_id}|{rule_version}|{scope_key}|{window_start}"
    return "a-" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def make_row(cfg, run_id, detected_at, rule_id, anomaly_type, source_table, window, scope_type, scope_key,
             metric, observed, baseline, baseline_kind, sample_size, evidence):
    ws, we = (t.strftime("%Y-%m-%d %H:%M:%S") for t in window)
    return {
        "run_id": run_id, "anomaly_id": anomaly_id(rule_id, cfg.rule_version, scope_key, ws),
        "rule_id": rule_id, "rule_version": cfg.rule_version, "anomaly_type": anomaly_type,
        "source_table": source_table, "window_start": ws, "window_end": we,
        "scope_type": scope_type, "scope_key": scope_key, "metric": metric,
        "observed_value": observed, "baseline_value": baseline, "baseline_kind": baseline_kind,
        "sample_size": sample_size, "episode_start": None, "episode_end": None,   # 연속 구간 합치기는 아직 없다
        "evidence_ref": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        "status": "OPEN", "detected_at": detected_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def r1_pg_failures(cfg, run_id, now, window, per_pg):
    """R1: 한 PG의 PG 원인 실패가 k건 이상이고, 그 PG 결제 시도 중 비율이 r1_rate 이상이면 이상."""
    rows = []
    for r in per_pg:
        fails, tries = r["pg_cause_failures"] or 0, r["attempts"] or 0
        if fails >= cfg.r1_k and tries and fails / tries >= cfg.r1_rate:
            rows.append(make_row(cfg, run_id, now, "R1_PG_FAILURES", "PG_FAILURE_SPIKE", "payment_attempts", window,
                                 "pg", r["pg"], "pg_cause_failures", fails, cfg.r1_k, "FIXED_THRESHOLD", tries,
                                 {"table": "payment_attempts", "pg": r["pg"], "pg_cause_failure_rate": round(fails / tries, 3)}))
    return rows


def r3_bronze_lag(cfg, run_id, now, window, lag_by_topic, snapshots_by_topic, ingest):
    """R3: 지연이 lag_sec 이상이거나, 측정 줄이 miss_min분 동안 하나도 없으면 이상. 유입량(R2)은 증거로만 붙인다."""
    rows = []
    for topic in cfg.topics:
        lag = lag_by_topic.get(topic)
        missing = snapshots_by_topic.get(topic, 0) == 0
        if (lag is not None and lag >= cfg.lag_sec) or missing:
            now_n, prev_n = ingest.get(topic, (0, 0))
            rows.append(make_row(cfg, run_id, now, "R3_BRONZE_LAG", "BRONZE_LAG_SPIKE", "bronze_lag_snapshots", window,
                                 "topic", topic, "bronze_lag_sec", lag, cfg.lag_sec, "FIXED_THRESHOLD", None,
                                 {"table": "bronze_lag_snapshots", "topic": topic, "no_snapshots": missing,
                                  "ingest_last_window": now_n, "ingest_prev_window": prev_n}))
    return rows


def r4_malformed(cfg, run_id, now, window, broken_by_topic, total_by_topic):
    """R4: 한 토픽의 깨진 메시지가 r4_min개 이상이고 비율이 r4_ratio 이상이면 이상 (현재 규칙 버전만 센 값)."""
    rows = []
    for topic in cfg.topics:
        broken, total = broken_by_topic.get(topic, 0), total_by_topic.get(topic, 0)
        if broken >= cfg.r4_min and total and broken / total >= cfg.r4_ratio:
            rows.append(make_row(cfg, run_id, now, "R4_MALFORMED", "MALFORMED_SPIKE", "malformed_messages", window,
                                 "topic", topic, "malformed_count", broken, cfg.r4_min, "FIXED_THRESHOLD", total,
                                 {"table": "malformed_events", "topic": topic, "rule_version": cfg.format_rule_version,
                                  "broken_ratio": round(broken / total, 3)}))
    return rows
