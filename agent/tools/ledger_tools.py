"""조사 에이전트가 쓰는 읽기 전용 도구 (원장 4개 + 정리 뷰 2개 + 이상 이력 + 재처리 기록).

도구 하나 = 질문 하나. 도구는 SQL을 만들어 울타리(guard.py)를 통과시킨 뒤에만 실행한다.
SQL은 Athena와 sqlite에서 모두 돌아가도록 기본 문법만 쓴다. 다른 점은 시각 표기뿐이라 `dialect`로 맞춘다.
"""
import re
from datetime import datetime, timedelta

from guard import GuardError, check_window, validate_sql

PGS = ("PG_A", "PG_B")
TOPICS = ("payments", "orders", "order-items", "member-events", "clickstream", "reviews.raw")
STALE_SECONDS = 120   # Gold B 문서의 고장 기준: 2분 넘게 안 쌓이면 멈춘 것


def _ts(dt: datetime, dialect: str) -> str:
    text = dt.strftime("%Y-%m-%d %H:%M:%S")
    return f"TIMESTAMP '{text}'" if dialect == "athena" else f"'{text}'"


def _pick(value, allowed, name):
    if value is None:
        return None
    if value not in allowed:
        raise GuardError(f"{name}은(는) {list(allowed)} 중 하나여야 합니다: {value!r}")
    return value


def _word(value, name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(value or "")):
        raise GuardError(f"{name} 형식이 맞지 않습니다: {value!r}")
    return value


def _range(col, a, b, dialect):
    return f"{col} >= {_ts(a, dialect)} AND {col} < {_ts(b, dialect)}"


# ---------- 도구 본체: 각각 (표시 이름, SQL 목록)을 돌려준다 ----------

def payment_summary(args, dialect):
    """PG별 결제 시도 수와 실패 수, 실패 원인(PG/고객/분류 안 됨)별 수. 시나리오 1 (PG 장애)."""
    a, b = check_window(args["window_start"], args["window_end"])
    pg = _pick(args.get("pg"), PGS, "pg")
    cond = _range("completed_at", a, b, dialect) + (f" AND pg = '{pg}'" if pg else "")
    return [("payment_summary", f"""SELECT pg,
       COUNT(*) AS attempts,
       SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures,
       SUM(CASE WHEN failure_cause = 'PG' THEN 1 ELSE 0 END) AS pg_cause_failures,
       SUM(CASE WHEN failure_cause = 'CUSTOMER' THEN 1 ELSE 0 END) AS customer_cause_failures,
       SUM(CASE WHEN failure_cause = 'UNKNOWN' THEN 1 ELSE 0 END) AS unknown_cause_failures
FROM gold_b.payment_attempts
WHERE {cond}
GROUP BY pg
ORDER BY pg
LIMIT 200""")]


def payment_failure_codes(args, dialect):
    """실패 코드별 건수. 어떤 코드로 쏠렸는지 본다 (PG_TIMEOUT인지 PG_ERROR인지 등)."""
    a, b = check_window(args["window_start"], args["window_end"])
    pg = _pick(args.get("pg"), PGS, "pg")
    cond = _range("completed_at", a, b, dialect) + " AND status = 'FAILED'" + (f" AND pg = '{pg}'" if pg else "")
    return [("payment_failure_codes", f"""SELECT pg, failure_cause, failure_code, COUNT(*) AS n,
       MIN(completed_at) AS first_seen
FROM gold_b.payment_attempts
WHERE {cond}
GROUP BY pg, failure_cause, failure_code
ORDER BY n DESC
LIMIT 200""")]


def payment_retry_impact(args, dialect):
    """장애가 주문에 준 영향: 실패를 겪은 주문 수와 재시도 시도 수 (order_id, attempt_no가 있을 때)."""
    a, b = check_window(args["window_start"], args["window_end"])
    pg = _pick(args.get("pg"), PGS, "pg")
    cond = _range("completed_at", a, b, dialect) + (f" AND pg = '{pg}'" if pg else "")
    return [("payment_retry_impact", f"""SELECT pg,
       COUNT(DISTINCT CASE WHEN failure_cause = 'PG' THEN order_id END) AS orders_with_pg_failure,
       SUM(CASE WHEN attempt_no > 1 THEN 1 ELSE 0 END) AS retry_attempts
FROM gold_b.payment_attempts
WHERE {cond}
GROUP BY pg
ORDER BY pg
LIMIT 200""")]


def ingest_volume(args, dialect):
    """토픽별 유입 메시지 수. 유입이 늘었는지 본다 (시나리오 2의 원인 구분)."""
    a, b = check_window(args["window_start"], args["window_end"])
    topic = _pick(args.get("topic"), TOPICS, "topic")
    cond = _range("kafka_timestamp", a, b, dialect) + (f" AND topic = '{topic}'" if topic else "")
    return [("ingest_volume", f"""SELECT topic, COUNT(*) AS messages,
       MIN(kafka_timestamp) AS first_message, MAX(kafka_timestamp) AS last_message
FROM gold_b.topic_messages
WHERE {cond}
GROUP BY topic
ORDER BY topic
LIMIT 200""")]


def bronze_lag(args, dialect):
    """토픽별 Bronze 적재 지연: 가장 오래 밀린 시간, 처리 위치가 멈췄는지, 커넥터 상태 (시나리오 2)."""
    a, b = check_window(args["window_start"], args["window_end"])
    topic = _pick(args.get("topic"), TOPICS, "topic")
    cond = _range("collected_at", a, b, dialect) + (f" AND topic = '{topic}'" if topic else "")
    return [("bronze_lag", f"""SELECT topic,
       COUNT(*) AS snapshots,
       MAX(lag_sec) AS max_lag_sec,
       MAX(lag_msgs) AS max_lag_msgs_in_one_partition,
       MIN(committed_offset) AS min_committed_offset,
       MAX(committed_offset) AS max_committed_offset,
       SUM(CASE WHEN connector_state <> 'RUNNING' THEN 1 ELSE 0 END) AS not_running_snapshots
FROM gold_b.bronze_lag_snapshots
WHERE {cond}
GROUP BY topic
ORDER BY topic
LIMIT 200""")]


def malformed_summary(args, dialect):
    """토픽·사유별 깨진 메시지 수 (현재 규칙 버전만 센다). 시나리오 3."""
    a, b = check_window(args["window_start"], args["window_end"])
    topic = _pick(args.get("topic"), TOPICS, "topic")
    version = _word(args.get("rule_version"), "rule_version")
    cond = _range("kafka_timestamp", a, b, dialect) + f" AND rule_version = '{version}'" + (f" AND topic = '{topic}'" if topic else "")
    return [("malformed_summary", f"""SELECT topic, reason, COUNT(*) AS broken_messages,
       MIN(kafka_timestamp) AS first_seen
FROM gold_b.malformed_messages
WHERE {cond}
GROUP BY topic, reason
ORDER BY broken_messages DESC
LIMIT 200""")]


def malformed_fields(args, dialect):
    """어느 필드가 왜 틀렸나, 언제부터인가, 재처리를 시작할 가장 이른 offset. 원문(raw_sample)은 읽지 않는다."""
    a, b = check_window(args["window_start"], args["window_end"])
    topic = _pick(args.get("topic"), TOPICS, "topic")
    version = _word(args.get("rule_version"), "rule_version")
    cond = _range("kafka_timestamp", a, b, dialect) + f" AND rule_version = '{version}'" + (f" AND topic = '{topic}'" if topic else "")
    return [("malformed_fields", f"""SELECT topic, field, reason, kafka_partition,
       COUNT(*) AS errors, MIN(kafka_timestamp) AS first_seen, MIN(kafka_offset) AS earliest_offset
FROM gold_b.malformed_events
WHERE {cond}
GROUP BY topic, field, reason, kafka_partition
ORDER BY errors DESC
LIMIT 200""")]


def ledger_reliability(args, dialect):
    """원장을 믿어도 되나: 메시지 누락, 중복, 적재 잡·수집기 멈춤 (신뢰성 쿼리 3개와 같은 질문)."""
    a, b = check_window(args["window_start"], args["window_end"])
    kt = _range("kafka_timestamp", a, b, dialect)
    key = "topic || '-' || CAST(kafka_partition AS VARCHAR) || '-' || CAST(kafka_offset AS VARCHAR)"
    return [
        ("gaps", f"""SELECT topic, kafka_partition, MIN(kafka_offset) AS first_offset, MAX(kafka_offset) AS last_offset,
       (MAX(kafka_offset) - MIN(kafka_offset) + 1) - COUNT(DISTINCT kafka_offset) AS missing_count
FROM gold_b.topic_messages
WHERE {kt}
GROUP BY topic, kafka_partition
HAVING (MAX(kafka_offset) - MIN(kafka_offset) + 1) - COUNT(DISTINCT kafka_offset) > 0
LIMIT 200"""),
        ("duplicate_messages", f"""SELECT COUNT(*) - COUNT(DISTINCT {key}) AS duplicate_rows
FROM gold_b.topic_messages
WHERE {kt}
LIMIT 1"""),
        ("duplicate_payments", f"""SELECT COUNT(*) - COUNT(DISTINCT payment_id) AS duplicate_rows
FROM gold_b.payment_events
WHERE {_range("completed_at", a, b, dialect)}
LIMIT 1"""),
        ("last_loaded", "SELECT MAX(loaded_at) AS last_loaded_at FROM gold_b.topic_messages LIMIT 1"),
        ("last_collected", "SELECT MAX(collected_at) AS last_collected_at FROM gold_b.bronze_lag_snapshots LIMIT 1"),
    ]


def list_anomalies(args, dialect):
    """탐지가 기록한 이상 이력. 같은 시간대를 여러 회차(run_id)가 판정했을 수 있으니 가장 큰 run_id가 최신이다."""
    a, b = check_window(args["window_start"], args["window_end"])
    cond = _range("window_start", a, b, dialect)
    return [("list_anomalies", f"""SELECT run_id, anomaly_id, rule_id, rule_version, anomaly_type, scope_key, window_start, window_end,
       metric, observed_value, baseline_value, sample_size, episode_start, episode_end, status
FROM gold_b.anomaly
WHERE {cond}
ORDER BY window_start, run_id DESC
LIMIT 200""")]


def reprocess_status(args, dialect):
    """재처리 요청의 진행 상태: 단계 기록을 최근 것부터. 마지막 줄의 step이 현재 상태다."""
    rid = _word(args.get("request_id"), "request_id")
    return [("reprocess_status", f"""SELECT request_id, step, at, actor, window_start, window_end, source, attempt, detail
FROM gold_b.reprocess_events
WHERE request_id = '{rid}'
ORDER BY at DESC
LIMIT 50""")]


# ---------- 결과 후처리 ----------

def _judge_reliability(results, now):
    last_loaded = (results["last_loaded"] or [{}])[0].get("last_loaded_at")
    last_collected = (results["last_collected"] or [{}])[0].get("last_collected_at")

    def status(value):
        if not value:
            return {"last_seen": None, "status": "UNKNOWN"}
        seen = datetime.fromisoformat(str(value).replace("T", " "))
        gap = (now - seen).total_seconds()
        return {"last_seen": str(value), "seconds_ago": int(gap), "status": "STOPPED" if gap > STALE_SECONDS else "OK"}

    return {
        "missing_messages": results["gaps"],
        "duplicate_messages": (results["duplicate_messages"] or [{}])[0].get("duplicate_rows", 0),
        "payment_duplicate_rows_info": (results["duplicate_payments"] or [{}])[0].get("duplicate_rows", 0),
        "ledger_writer": status(last_loaded),
        "lag_collector": status(last_collected),
        "note": "적재 문제는 missing_messages와 duplicate_messages(topic_messages 기준)로만 판단한다. payment_duplicate_rows_info는 참고값이며 같은 payment_id 중복은 정상이다(뷰가 걸러 줌). STOPPED는 데이터 이상이 아니라 관제(적재 잡·수집기) 고장일 수 있어 원인 결론과 섞지 않는다.",
    }


# ---------- 도구 목록 (Bedrock tool 정의 모양) ----------

def _spec(name, description, props, required):
    return {"toolSpec": {"name": name, "description": description,
                         "inputSchema": {"json": {"type": "object", "properties": props, "required": required}}}}


_WIN = {"window_start": {"type": "string", "description": "시작 시각(UTC, 예: 2026-10-20T15:00:00)"},
        "window_end": {"type": "string", "description": "끝 시각(UTC). 시작에서 6시간 이내"}}
_PG = {"pg": {"type": "string", "enum": list(PGS), "description": "특정 PG만 보려면"}}
_TOPIC = {"topic": {"type": "string", "enum": list(TOPICS), "description": "특정 토픽만 보려면"}}
_RULE = {"rule_version": {"type": "string", "description": "현재 형식 검사 규칙 버전(예: v1.0). 섞어 세지 않게 필수"}}

TOOLS = {
    "payment_summary": (payment_summary, _spec("payment_summary", payment_summary.__doc__, {**_WIN, **_PG}, ["window_start", "window_end"])),
    "payment_failure_codes": (payment_failure_codes, _spec("payment_failure_codes", payment_failure_codes.__doc__, {**_WIN, **_PG}, ["window_start", "window_end"])),
    "payment_retry_impact": (payment_retry_impact, _spec("payment_retry_impact", payment_retry_impact.__doc__, {**_WIN, **_PG}, ["window_start", "window_end"])),
    "ingest_volume": (ingest_volume, _spec("ingest_volume", ingest_volume.__doc__, {**_WIN, **_TOPIC}, ["window_start", "window_end"])),
    "bronze_lag": (bronze_lag, _spec("bronze_lag", bronze_lag.__doc__, {**_WIN, **_TOPIC}, ["window_start", "window_end"])),
    "malformed_summary": (malformed_summary, _spec("malformed_summary", malformed_summary.__doc__, {**_WIN, **_TOPIC, **_RULE}, ["window_start", "window_end", "rule_version"])),
    "malformed_fields": (malformed_fields, _spec("malformed_fields", malformed_fields.__doc__, {**_WIN, **_TOPIC, **_RULE}, ["window_start", "window_end", "rule_version"])),
    "ledger_reliability": (ledger_reliability, _spec("ledger_reliability", ledger_reliability.__doc__, _WIN, ["window_start", "window_end"])),
    "list_anomalies": (list_anomalies, _spec("list_anomalies", list_anomalies.__doc__, _WIN, ["window_start", "window_end"])),
    "reprocess_status": (reprocess_status, _spec("reprocess_status", reprocess_status.__doc__, {"request_id": {"type": "string", "description": "재처리 요청 번호"}}, ["request_id"])),
}
TOOL_SPECS = [spec for _, spec in TOOLS.values()]


def run_tool(name, args, execute, dialect="athena", now=None):
    """도구를 실행한다. execute(sql) -> 줄 목록(dict). 울타리를 통과한 SQL만 execute에 넘긴다."""
    if name not in TOOLS:
        raise GuardError(f"없는 도구입니다: {name}")
    builder, _ = TOOLS[name]
    queries = builder(args, dialect)
    results = {}
    for label, sql in queries:
        results[label] = execute(validate_sql(sql))
    if name == "ledger_reliability":
        return _judge_reliability(results, now or datetime.utcnow())
    label = queries[0][0]
    return {"rows": results[label], "row_limit": 200}
