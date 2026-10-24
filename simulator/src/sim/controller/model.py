"""컨트롤러의 사건(장애) 종류, 상한, 진행 중 사건. 값은 이 파일 한 곳에 둔다."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

# 사건 종류
PG_OUTAGE = "PG_OUTAGE"
INGEST_LAG = "INGEST_LAG"  # burst 모드 (적재 지연이 목적)
TRAFFIC_SURGE = "TRAFFIC_SURGE"  # medium 모드 (약한 급증)
DATA_POLLUTION = "DATA_POLLUTION"
OPERATOR_PAUSE = "OPERATOR_PAUSE"  # running=false. 사건은 아니지만 정답표에 남긴다
SINK_PAUSE = "SINK_PAUSE"  # S3 Sink 정지 (기록만. 정지·재개는 사람이 kubectl로)
MODE_INCIDENTS: dict[str, str] = {"medium": TRAFFIC_SURGE, "burst": INGEST_LAG}

# S3 Sink 정지: 컨트롤러는 EKS 커넥터를 건드리지 못한다. 자동 종료 없음(재개 확인 뒤 end)
SINK_CONNECTORS: tuple[str, ...] = ("bronze-s3-sink-v2",)
DEFAULT_SINK_PAUSE_MINUTES = 25  # R3 기준 1200초를 확실히 넘기는 20분 + 여유
MAX_SINK_PAUSE_MINUTES = 60

# PG 장애 (PG 이름은 behavior.params.PGS와 같다. 테스트가 확인한다)
PGS: tuple[str, ...] = ("PG_A", "PG_B")
DEFAULT_PG_EXTRA_FAIL = 0.85
DEFAULT_PG_OUTAGE_MINUTES = 10
MAX_PG_OUTAGE_MINUTES = 60

# 데이터 오염: DB 제약은 통과하지만 업무 규칙을 어기는 행
ORDER_TOTAL_MISMATCH = "ORDER_TOTAL_MISMATCH"  # 주문 총액 ≠ 항목 합계, 결제 금액
DUPLICATE_SUCCESS_PAYMENT = "DUPLICATE_SUCCESS_PAYMENT"  # 한 주문에 SUCCESS 결제 2건
POLLUTION_KINDS: tuple[str, ...] = (ORDER_TOTAL_MISMATCH, DUPLICATE_SUCCESS_PAYMENT)
DEFAULT_POLLUTION_COUNT = 30
MAX_POLLUTION_COUNT = 500  # 정답표에 주문 id를 모두 싣는 상한
TOTAL_MISMATCH_DELTA = 10_000  # 원

# 자동 복귀 (분)
DEFAULT_MEDIUM_MINUTES = 60.0
DEFAULT_BURST_MINUTES = 15.0

# 정답표
SCHEMA_VERSION = 1
START, END = "start", "end"
ENDED_BY = ("timer", "manual", "shutdown", "complete", "failed")


@dataclass(frozen=True)
class Incident:
    """진행 중인 사건. ends_at이 있으면 그 시각에 tick()이 자동으로 끝낸다."""

    incident_id: str
    type: str
    started_at: datetime
    ends_at: datetime | None
    params: Mapping[str, object] = field(default_factory=dict, hash=False)


def utc_text(at: datetime) -> str:
    """정답표 시각: YYYY-MM-DDTHH:MM:SSZ (UTC)."""
    if at.tzinfo is None:
        raise ValueError("시각은 시간대 정보가 있어야 합니다.")
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_stamp(at: datetime) -> str:
    """정답표 파일명 앞부분: YYYYMMDDTHHMMSSZ (UTC)."""
    return at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
