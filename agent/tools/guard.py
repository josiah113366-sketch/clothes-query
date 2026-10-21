"""조사 에이전트가 보내는 SQL을 실행 전에 검사한다 (읽기 전용 울타리).

에이전트가 쓰는 도구는 이 울타리를 통과한 SELECT만 실행한다. 통과하지 못하면 실행하지 않고 이유를 알려 준다.
"""
import re
from datetime import datetime

ALLOWED_TABLES = {
    "gold_b.payment_events", "gold_b.payment_attempts", "gold_b.topic_messages",
    "gold_b.bronze_lag_snapshots", "gold_b.malformed_events", "gold_b.malformed_messages",
    "gold_b.reprocess_events", "gold_b.anomaly",
}
FORBIDDEN_WORDS = ("insert", "update", "delete", "drop", "alter", "create", "merge", "grant", "revoke",
                   "call", "unload", "copy", "truncate", "msck", "set", "use", "explain", "describe", "show")
FORBIDDEN_TEXT = ("ground_truth", "incident_log", "raw_sample")   # 정답표와 원문 일부는 에이전트가 못 읽는다
MAX_ROWS = 200            # 한 번에 돌려받는 줄 수 한도 (임의 값)
MAX_WINDOW_HOURS = 6      # 한 번에 조회하는 시간 범위 한도 (임의 값)


class GuardError(ValueError):
    """울타리를 통과하지 못한 SQL이나 인자."""


def validate_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    low = s.lower()
    if ";" in s:
        raise GuardError("문장이 여러 개입니다. 한 번에 SELECT 하나만 보낼 수 있습니다.")
    if not (low.startswith("select") or low.startswith("with")):
        raise GuardError("SELECT만 실행할 수 있습니다.")
    for w in FORBIDDEN_WORDS:
        if re.search(rf"\b{w}\b", low):
            raise GuardError(f"허용되지 않는 명령어가 있습니다: {w}")
    for t in FORBIDDEN_TEXT:
        if t in low:
            raise GuardError(f"읽을 수 없는 대상입니다: {t}")
    tables = set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*)", low))
    if not tables:
        raise GuardError("읽을 표(gold_b.표이름)가 없습니다.")
    bad = tables - ALLOWED_TABLES
    if bad:
        raise GuardError(f"읽을 수 없는 표입니다: {sorted(bad)}")
    m = re.search(r"\blimit\s+(\d+)\s*$", low)
    if not m:
        raise GuardError("맨 끝에 LIMIT이 필요합니다.")
    if int(m.group(1)) > MAX_ROWS:
        raise GuardError(f"LIMIT은 {MAX_ROWS} 이하여야 합니다.")
    return s


def parse_time(value: str) -> datetime:
    """'2026-10-20T15:00:00' 또는 '2026-10-20 15:00:00' (UTC)만 받는다."""
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", ""))
    except ValueError as e:
        raise GuardError(f"시각 형식이 맞지 않습니다: {value!r} (예: 2026-10-20T15:00:00, UTC)") from e


def check_window(start: str, end: str) -> tuple[datetime, datetime]:
    a, b = parse_time(start), parse_time(end)
    if b <= a:
        raise GuardError("끝 시각은 시작 시각보다 뒤여야 합니다.")
    if (b - a).total_seconds() > MAX_WINDOW_HOURS * 3600:
        raise GuardError(f"한 번에 {MAX_WINDOW_HOURS}시간까지만 조회할 수 있습니다. 범위를 나눠서 물어보세요.")
    return a, b
