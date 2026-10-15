"""S3 Sink 검증 로직. S3·Kafka·Connect를 부르지 않는 순수 함수와 집계기.

파일은 한 줄씩 add_file()로 넣고 원문을 쌓아 두지 않는다. 남기는 것은 집계값과 member_id 집합뿐이다.
결과 문자열에는 회원 값을 싣지 않는다 (필드 이름, 건수, 객체 키(경로), 최대 5개의 member_id만).
필드·PII·시각 검사는 sim.cdc.checks의 EventChecker를 그대로 쓴다 (토픽과 같은 기준).
"""

import json
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sim.cdc.checks import MAX_EXAMPLES, CheckResult, EventChecker, parse_utc
from sim.cdc.connect import is_running, states
from sim.cdc.params import FORBIDDEN_VALUE_PATTERNS
from sim.sink import params

_KEY_REGEX = re.compile(params.KEY_PATTERN)
_CREDENTIAL = re.compile(params.CREDENTIAL_PATTERN)
_PII_KEY_PATTERNS = [re.compile(p) for p in FORBIDDEN_VALUE_PATTERNS]


class S3ObjectLike(Protocol):
    key: str
    size: int
    last_modified: datetime


# --- 커넥터 설정 파일 검사 (안전장치) ---


def config_problems(config: Mapping[str, Any], source_topic: str) -> list[str]:
    """등록 전 안전장치에 걸리는 이유 목록. 비어 있으면 통과다."""
    problems: list[str] = []

    if config.get("topics") != source_topic:
        problems.append(f"topics는 source 커넥터의 토픽 {source_topic} 하나여야 합니다.")

    for key in config:
        lowered = str(key).lower()
        if (
            lowered in params.FORBIDDEN_CONFIG_KEYS
            or "secret" in lowered
            or "access.key" in lowered
        ):
            problems.append(
                "자격 증명 설정 키가 있습니다 (환경 변수의 기본 자격 증명 체인만 씁니다)."
            )
            break
    if any(_CREDENTIAL.search(str(value)) for value in config.values()):
        problems.append("자격 증명으로 보이는 문자열(AKIA...)이 있습니다.")

    if config.get("s3.bucket.name") != params.BUCKET_REFERENCE:
        problems.append(
            f"s3.bucket.name은 {params.BUCKET_REFERENCE} 참조여야 합니다 (버킷 이름을 파일에 쓰지 않습니다)."
        )
    if config.get("s3.region") != params.REGION_REFERENCE:
        problems.append(f"s3.region은 {params.REGION_REFERENCE} 참조여야 합니다.")

    if not str(config.get("partitioner.class", "")).endswith(params.REQUIRED_PARTITIONER_SUFFIX):
        problems.append("partitioner.class는 시간 기반(TimeBasedPartitioner)이어야 합니다.")
    if config.get("timezone") != params.REQUIRED_TIMEZONE:
        problems.append(f"timezone은 {params.REQUIRED_TIMEZONE}이어야 합니다.")
    if config.get("path.format") != params.REQUIRED_PATH_FORMAT:
        problems.append(f"path.format은 {params.REQUIRED_PATH_FORMAT}이어야 합니다.")
    if not str(config.get("format.class", "")).endswith(params.REQUIRED_FORMAT_SUFFIX):
        problems.append("format.class는 JSON 형식(JsonFormat)이어야 합니다.")
    return problems


# --- 객체 키 ---


@dataclass(frozen=True)
class ParsedKey:
    dt: date
    partition: int
    start_offset: int


def parse_key(key: str) -> ParsedKey | None:
    match = _KEY_REGEX.fullmatch(key)
    if match is None:
        return None
    try:
        dt = date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError:
        return None
    return ParsedKey(dt, int(match["partition"]), int(match["offset"]))


@dataclass(frozen=True)
class _FileInfo:
    parsed: ParsedKey
    rows: int
    size: int


def key_member_id(key: bytes | None) -> str | None:
    """토픽 메시지 키(JSON)에서 member_id만 꺼낸다. 읽을 수 없으면 None."""
    try:
        parsed = json.loads((key or b"").decode("utf-8", errors="replace"))
    except ValueError:
        return None
    member_id = parsed.get("member_id") if isinstance(parsed, dict) else parsed
    return member_id if isinstance(member_id, str) else None


def _utc_date(value: object) -> date | None:
    parsed = parse_utc(value)
    return parsed.date() if parsed else None


def _ts_ms_date(value: object) -> date | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


class SinkChecker:
    """S3 파일을 하나씩 집계한다."""

    def __init__(
        self,
        topic_offsets: Mapping[int, tuple[int, int]],
        region_names: Collection[str],
        today: date,
    ) -> None:
        self.topic_offsets = dict(topic_offsets)
        self.today = today
        self.events = EventChecker(region_names)
        self.bad_paths: list[str] = []
        self.object_count = 0
        self.array_files: list[str] = []
        self.blank_lines = 0
        self.key_pii_hits = 0
        self.files: list[_FileInfo] = []
        self.sizes: list[int] = []
        self.dt_too_early: list[str] = []
        self.dt_in_future: list[str] = []
        self.rows = 0

    def add_file(self, obj: S3ObjectLike, lines: Iterable[bytes]) -> None:
        self.object_count += 1
        self.sizes.append(obj.size)
        parsed = parse_key(obj.key)
        if parsed is None:
            self.bad_paths.append(obj.key)
        if any(pattern.search(obj.key) for pattern in _PII_KEY_PATTERNS):
            self.key_pii_hits += 1

        rows = 0
        max_created: date | None = None
        max_source: date | None = None
        first = True
        for line in lines:
            if first:
                first = False
                if line.lstrip().startswith(b"["):
                    self.array_files.append(obj.key)
            if not line.strip():
                self.blank_lines += 1
                continue
            rows += 1
            member_key = self._key_for(line)
            self.events.add(member_key, line)
            created, source = self._dates(line)
            if created and (max_created is None or created > max_created):
                max_created = created
            if source and (max_source is None or source > max_source):
                max_source = source
        self.rows += rows

        if parsed is None:
            return
        self.files.append(_FileInfo(parsed, rows, obj.size))
        newest = max((d for d in (max_created, max_source) if d), default=None)
        if newest is not None and parsed.dt < newest:
            self.dt_too_early.append(obj.key)
        if parsed.dt > self.today + timedelta(days=params.FUTURE_DAYS_ALLOWED):
            self.dt_in_future.append(obj.key)

    @staticmethod
    def _key_for(line: bytes) -> bytes | None:
        """토픽 검사기는 메시지 키를 비교한다. 파일에는 키가 없어서 값의 member_id로 만든다."""
        try:
            event = json.loads(line)
        except ValueError:
            return None
        member_id = event.get("member_id") if isinstance(event, dict) else None
        if not isinstance(member_id, str):
            return None
        return json.dumps({"member_id": member_id}).encode()

    @staticmethod
    def _dates(line: bytes) -> tuple[date | None, date | None]:
        try:
            event = json.loads(line)
        except ValueError:
            return None, None
        if not isinstance(event, dict):
            return None, None
        return _utc_date(event.get("created_at")), _ts_ms_date(event.get("__source_ts_ms"))

    # --- 결과 ---

    def results(self, topic_ids: Collection[str]) -> list[CheckResult]:
        """S3 내용으로 정하는 항목 (2~11). 1번(커넥터)은 check_connector가 만든다."""
        base = {r.number: r for r in self.events.results()}
        return [
            self._path_result(),
            self._format_result(),
            replace(base[4], number=4),
            self._pii_result(base[5]),
            replace(base[6], number=6),
            self._dt_result(),
            self._offset_result(),
            self._rows_result(),
            self._members_result(topic_ids),
            self._size_report(),
        ]

    def _path_result(self) -> CheckResult:
        examples = ", ".join(self.bad_paths[:MAX_EXAMPLES])
        detail = f"객체 {self.object_count:,}개 중 형식이 어긋난 키 {len(self.bad_paths):,}개"
        if examples:
            detail += f" (예: {examples})"
        return CheckResult(2, "경로", not self.bad_paths, detail)

    def _format_result(self) -> CheckResult:
        broken = self.events.unparseable.count
        passed = not self.array_files and not self.blank_lines and not broken
        detail = (
            f"배열 파일 {len(self.array_files):,}개, 빈 줄 {self.blank_lines:,}개, "
            f"깨진 줄 {broken:,}개"
        )
        if self.array_files:
            detail += f" (예: {', '.join(self.array_files[:MAX_EXAMPLES])})"
        return CheckResult(3, "형식", passed, detail)

    def _pii_result(self, from_lines: CheckResult) -> CheckResult:
        passed = from_lines.passed and self.key_pii_hits == 0
        if passed:
            return CheckResult(
                5,
                "PII 없음",
                True,
                f"파일 원문 {self.events.total:,}줄과 객체 키 {self.object_count:,}개에서 0건",
            )
        detail = from_lines.detail if not from_lines.passed else "파일 원문 0건"
        return CheckResult(5, "PII 없음", False, f"{detail}, 객체 키 {self.key_pii_hits:,}개")

    def _dt_result(self) -> CheckResult:
        passed = not self.dt_too_early and not self.dt_in_future
        detail = (
            f"수집일이 데이터 시각보다 이른 파일 {len(self.dt_too_early):,}개, "
            f"오늘(UTC)+{params.FUTURE_DAYS_ALLOWED}일을 넘는 파일 {len(self.dt_in_future):,}개"
        )
        bad = (self.dt_too_early + self.dt_in_future)[:MAX_EXAMPLES]
        if bad:
            detail += f" (예: {', '.join(bad)})"
        return CheckResult(7, "날짜 폴더", passed, detail)

    def _offset_result(self) -> CheckResult:
        by_partition: dict[int, list[_FileInfo]] = defaultdict(list)
        for info in self.files:
            by_partition[info.parsed.partition].append(info)

        gaps: list[str] = []
        gap_total = 0
        overlap_total = 0
        for partition, (low, high) in sorted(self.topic_offsets.items()):
            expected_next = low
            for info in sorted(
                by_partition.get(partition, []), key=lambda i: i.parsed.start_offset
            ):
                start = info.parsed.start_offset
                if start > expected_next:
                    gap_total += start - expected_next
                    gaps.append(f"파티션 {partition}: {expected_next}~{start - 1}")
                elif start < expected_next:
                    overlap_total += min(expected_next, start + info.rows) - start
                expected_next = max(expected_next, start + info.rows)
            if expected_next < high:
                gap_total += high - expected_next
                gaps.append(f"파티션 {partition}: {expected_next}~{high - 1}")
        detail = f"빈 구간 {len(gaps):,}곳({gap_total:,}건), 겹친 구간 {overlap_total:,}건(중복 후보, 실패 아님)"
        if gaps:
            detail += f" (예: {', '.join(gaps[:MAX_EXAMPLES])})"
        return CheckResult(8, "offset 연속성", not gaps, detail)

    def _rows_result(self) -> CheckResult:
        expected = sum(high - low for low, high in self.topic_offsets.values())
        passed = self.rows >= expected
        extra = max(self.rows - expected, 0)
        detail = f"S3 {self.rows:,}줄, 토픽 {expected:,}건"
        if passed:
            detail += f", 중복 {extra:,}건 (at-least-once)"
        else:
            detail += f", 부족 {expected - self.rows:,}건"
        return CheckResult(9, "행 수", passed, detail)

    def _members_result(self, topic_ids: Collection[str]) -> CheckResult:
        s3_ids, kafka_ids = self.events.all_ids, set(topic_ids)
        only_s3, only_kafka = s3_ids - kafka_ids, kafka_ids - s3_ids
        passed = not only_s3 and not only_kafka
        detail = f"S3 {len(s3_ids):,}명, 토픽 {len(kafka_ids):,}명"
        if not passed:
            detail += f", S3에만 {len(only_s3):,}명, 토픽에만 {len(only_kafka):,}명"
            shown = sorted(only_s3)[:MAX_EXAMPLES] + sorted(only_kafka)[:MAX_EXAMPLES]
            detail += f" (예: {', '.join(shown[:MAX_EXAMPLES])})"
        return CheckResult(10, "회원 대조", passed, detail)

    def _size_report(self) -> CheckResult:
        if not self.sizes:
            return CheckResult(11, "파일 크기", True, "파일 없음 (보고만 함)")
        small = sum(1 for size in self.sizes if size < params.SMALL_FILE_BYTES)
        detail = (
            f"파일 {len(self.sizes):,}개, 가장 작은 {min(self.sizes):,}B, "
            f"평균 {sum(self.sizes) // len(self.sizes):,}B (보고만 함)"
        )
        if small * 2 > len(self.sizes):
            detail += f" — 경고: {params.SMALL_FILE_BYTES:,}B보다 작은 파일이 {small:,}개로 절반을 넘습니다"
        return CheckResult(11, "파일 크기", True, detail)


# --- 커넥터와 진행 상태 ---


def check_connector(
    status: Mapping[str, Any] | None, config: Mapping[str, Any] | None, source_topic: str
) -> CheckResult:
    """1번: 커넥터·task RUNNING, 등록된 설정의 topics가 source 토픽과 같다."""
    if status is None or config is None:
        return CheckResult(1, "커넥터", False, "커넥터가 등록되어 있지 않습니다")
    connector, tasks = states(status)
    problems = []
    if not is_running(status):
        problems.append(f"커넥터 {connector}, task {', '.join(tasks) or '없음'}")
    if config.get("topics") != source_topic:
        problems.append("topics가 source 토픽과 다릅니다")
    if problems:
        return CheckResult(1, "커넥터", False, "; ".join(problems))
    return CheckResult(1, "커넥터", True, "커넥터 RUNNING, task RUNNING, topics 일치")


def writing_in_progress(
    lag: int | None, last_modified: datetime | None, now: datetime
) -> str | None:
    """아직 쓰는 중이면 이유, 아니면 None. 실패가 아니라 '잠시 뒤 다시'로 다룬다."""
    if lag is None:
        return "커넥터가 읽은 위치를 아직 모릅니다"
    if lag > 0:
        return f"커넥터가 {lag:,}건 밀려 있습니다"
    if last_modified is not None and (now - last_modified).total_seconds() < params.QUIET_SECONDS:
        return f"마지막 파일이 {params.QUIET_SECONDS}초 안에 만들어졌습니다"
    return None
