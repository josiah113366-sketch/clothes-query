"""CDC 확인에 쓰는 설계 수치. 값은 이 파일 한 곳에만 둔다 (커넥터 쪽은 connectors/member-source.json)."""

from sim.member.params import AGE_BANDS

CONNECTOR_NAME = "member-source"
TOPIC = "members-events"
TOPIC_PREFIX = "cdc"
HEARTBEAT_TOPIC = f"__debezium-heartbeat.{TOPIC_PREFIX}"
SLOT_NAME = "member_slot"
PUBLICATION_NAME = "member_pub"
SOURCE_TABLE = "public.members"
DEFAULT_CONFIG_PATH = "../connectors/member-source.json"

# Bronze에 들어가는 컬럼 10개. 이것만 내보내고 나머지(PII)는 내보내지 않는다.
BRONZE_COLUMNS: tuple[str, ...] = (
    "member_id",
    "signup_at",
    "signup_channel",
    "gender",
    "age_band",
    "region_sigungu",
    "marketing_consent",
    "status",
    "withdrawn_at",
    "created_at",
)
TIME_COLUMNS: tuple[str, ...] = ("signup_at", "created_at", "withdrawn_at")

# Debezium(ExtractNewRecordState)이 붙이는 관리 컬럼. 이름은 실제 토픽에서 확인한 값이다.
OP_COLUMN = "__op"
SOURCE_TS_COLUMN = "__source_ts_ms"
SNAPSHOT_COLUMN = "__source_snapshot"
MANAGED_COLUMNS: tuple[str, ...] = (OP_COLUMN, SOURCE_TS_COLUMN, SNAPSHOT_COLUMN)

# 토픽에 절대 있으면 안 되는 필드 이름과 값 모양
FORBIDDEN_FIELDS: tuple[str, ...] = ("name", "email", "phone", "birth_date", "password_hash")
FORBIDDEN_VALUE_PATTERNS: tuple[str, ...] = (
    r"@example\.com",
    r"010-\d{4}-\d{4}",
    r"\$2b\$12\$",
)

ALLOWED_OPS = frozenset({"r", "c", "u"})
# 실제 Debezium 3.7 출력: 스냅샷 첫 행은 "first", 마지막 행은 "last", 나머지는 "true"
SNAPSHOT_VALUES_FOR_R = frozenset({"true", "first", "last"})
# 실제 Debezium 3.7 출력: 스냅샷이 아닌 이벤트(c)는 값이 null이다. "false"도 받아 준다.
SNAPSHOT_VALUES_FOR_C = frozenset({None, "false"})
GENDERS = frozenset({"F", "M"})
CHANNELS = frozenset({"web", "app"})
STATUSES = frozenset({"ACTIVE", "WITHDRAWN"})
AGE_BAND_VALUES = frozenset(AGE_BANDS)

# 기본 기대값과 확인 범위
DEFAULT_SNAPSHOT_EXPECTED = 100_000
SAMPLE_SIZE = 1_000
# r 이벤트의 signup_at 범위: KST [2026-08-01, 2026-10-01) = UTC [2026-07-31 15:00, 2026-09-30 15:00)
SNAPSHOT_SIGNUP_FROM_UTC = "2026-07-31T15:00:00"
SNAPSHOT_SIGNUP_TO_UTC = "2026-09-30T15:00:00"

# 기다림 (초)
SETUP_WAIT_SECONDS = 60
CONSUME_IDLE_SECONDS = 60
SLOT_DROP_RETRY_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 10
