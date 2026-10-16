"""CDC 검증 로직. Kafka·DB를 부르지 않는 순수 함수와 집계기.

메시지는 하나씩 add()로 넣고 원문을 쌓아 두지 않는다. 남기는 것은 집계값, member_id 집합,
샘플 회원의 이벤트뿐이다. 결과 문자열에는 회원 값을 싣지 않는다 (필드 이름, 건수, 최대 5개의 member_id만).
"""

import json
import re
import uuid
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sim.cdc import params
from sim.cdc.connect import config_problems, is_running, states

MAX_EXAMPLES = 5
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")
_PII_PATTERNS = {pattern: re.compile(pattern) for pattern in params.FORBIDDEN_VALUE_PATTERNS}
# member_id(UUID) 안에서 우연히 `010-1234-5678` 모양이 나올 수 있다 (UUID 약 4,000개에 하나).
# 값 모양 검사에서는 UUID 모양을 먼저 지운다. 전화번호는 UUID 모양일 수 없다.
_UUID_SHAPE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_EXPECTED_KEYS = frozenset(params.BRONZE_COLUMNS) | frozenset(params.MANAGED_COLUMNS)
_SNAPSHOT_FROM = datetime.fromisoformat(params.SNAPSHOT_SIGNUP_FROM_UTC).replace(tzinfo=UTC)
_SNAPSHOT_TO = datetime.fromisoformat(params.SNAPSHOT_SIGNUP_TO_UTC).replace(tzinfo=UTC)


@dataclass(frozen=True)
class CheckResult:
    number: int
    name: str
    passed: bool
    detail: str
    skipped: bool = False


def _safe_name(name: str) -> str:
    """필드 이름만 보여 준다. 이름처럼 생기지 않은 문자열은 생략한다."""
    return name if _FIELD_NAME.fullmatch(name) else "(이름 생략)"


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def parse_utc(value: object) -> datetime | None:
    """`Z`로 끝나는 UTC 시각 문자열만 받는다. 그 밖에는 None."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _key_member_id(key: object) -> str | None:
    if isinstance(key, dict):
        key = key.get("member_id")
    return key if isinstance(key, str) else None


@dataclass
class _Tally:
    count: int = 0
    examples: list[str] = field(default_factory=list)

    def add(self, member_id: str | None) -> None:
        self.count += 1
        if member_id and _is_uuid(member_id) and len(self.examples) < MAX_EXAMPLES:
            self.examples.append(member_id)

    def text(self) -> str:
        shown = f" (예: {', '.join(self.examples)})" if self.examples else ""
        return f"{self.count:,}건{shown}"


class EventChecker:
    """토픽 메시지를 하나씩 집계한다."""

    def __init__(
        self,
        region_names: Collection[str],
        sample_ids: Collection[str] = (),
        snapshot_expected: int = params.DEFAULT_SNAPSHOT_EXPECTED,
        live_expected: int | None = None,
    ) -> None:
        self.regions = frozenset(region_names)
        self.sample_ids = frozenset(sample_ids)
        self.snapshot_expected = snapshot_expected
        self.live_expected = live_expected

        self.total = 0
        self.ops: Counter[str] = Counter()
        self.ids_by_op: dict[str, set[str]] = {"r": set(), "c": set()}
        self.all_ids: set[str] = set()
        self.sample_events: dict[str, dict[str, Any]] = {}

        self.unparseable = _Tally()
        self.bad_keys = _Tally()
        self.key_field_problems: Counter[str] = Counter()
        self.pii_hits: Counter[str] = Counter()
        self.bad_time = _Tally()
        self.bad_snapshot_range = _Tally()
        self.bad_shape = _Tally()
        self.shape_fields: Counter[str] = Counter()
        self.key_mismatch = _Tally()
        self.bad_snapshot_flag = _Tally()
        self.duplicates = _Tally()

    # --- 하나씩 집계 ---

    def add(self, key: bytes | None, value: bytes | None) -> None:
        self.total += 1
        text = (value or b"").decode("utf-8", errors="replace")
        key_text = (key or b"").decode("utf-8", errors="replace")
        raw = f"{key_text}\n{text}"
        for field_name in params.FORBIDDEN_FIELDS:
            if f'"{field_name}"' in raw:
                self.pii_hits[f'필드 "{field_name}"'] += 1
        without_ids = _UUID_SHAPE.sub("", raw)
        for pattern, regex in _PII_PATTERNS.items():
            if regex.search(without_ids):
                self.pii_hits[f"값 모양 {pattern}"] += 1

        try:
            event = json.loads(text)
            parsed_key = json.loads(key_text) if key_text else None
        except ValueError:
            self.unparseable.add(None)
            return
        if not isinstance(event, dict):
            self.unparseable.add(None)
            return

        member_id = event.get("member_id") if isinstance(event.get("member_id"), str) else None
        self._check_fields(event, member_id)
        op = event.get(params.OP_COLUMN)
        self.ops[str(op)] += 1
        self._check_key(parsed_key, member_id)
        self._check_times(event, op, member_id)
        self._check_shape(event, member_id)
        self._check_snapshot_flag(event, op, member_id)
        self._track_ids(event, op, member_id)

    def _check_fields(self, event: Mapping[str, Any], member_id: str | None) -> None:
        keys = set(event)
        if keys != _EXPECTED_KEYS:
            self.bad_keys.add(member_id)
            for name in keys - _EXPECTED_KEYS:
                self.key_field_problems[f"더 있음: {_safe_name(name)}"] += 1
            for name in _EXPECTED_KEYS - keys:
                self.key_field_problems[f"모자람: {name}"] += 1

    def _check_key(self, parsed_key: object, member_id: str | None) -> None:
        if _key_member_id(parsed_key) != member_id or member_id is None:
            self.key_mismatch.add(member_id)

    def _check_times(self, event: Mapping[str, Any], op: object, member_id: str | None) -> None:
        bad = False
        for column in params.TIME_COLUMNS:
            value = event.get(column)
            if value is None and column == "withdrawn_at":
                continue
            if parse_utc(value) is None:
                bad = True
        if bad:
            self.bad_time.add(member_id)
        elif op == "r":
            signup = parse_utc(event.get("signup_at"))
            if signup is None or not _SNAPSHOT_FROM <= signup < _SNAPSHOT_TO:
                self.bad_snapshot_range.add(member_id)

    def _check_shape(self, event: Mapping[str, Any], member_id: str | None) -> None:
        checks = {
            "member_id": _is_uuid(event.get("member_id")),
            "gender": event.get("gender") in params.GENDERS,
            "signup_channel": event.get("signup_channel") in params.CHANNELS,
            "age_band": event.get("age_band") in params.AGE_BAND_VALUES,
            "status": event.get("status") in params.STATUSES,
            "marketing_consent": isinstance(event.get("marketing_consent"), bool),
            "region_sigungu": event.get("region_sigungu") in self.regions,
            params.SOURCE_TS_COLUMN: isinstance(event.get(params.SOURCE_TS_COLUMN), int)
            and not isinstance(event.get(params.SOURCE_TS_COLUMN), bool),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            self.bad_shape.add(member_id)
            self.shape_fields.update(failed)

    def _check_snapshot_flag(
        self, event: Mapping[str, Any], op: object, member_id: str | None
    ) -> None:
        flag = event.get(params.SNAPSHOT_COLUMN)
        wrong_r = op == "r" and flag not in params.SNAPSHOT_VALUES_FOR_R
        wrong_c = op == "c" and flag not in params.SNAPSHOT_VALUES_FOR_C
        if wrong_r or wrong_c:
            self.bad_snapshot_flag.add(member_id)

    def _track_ids(self, event: Mapping[str, Any], op: object, member_id: str | None) -> None:
        if member_id is None:
            return
        self.all_ids.add(member_id)
        if op in self.ids_by_op:
            seen = self.ids_by_op[str(op)]
            if member_id in seen:
                self.duplicates.add(member_id)
            seen.add(member_id)
        if member_id in self.sample_ids:
            self.sample_events[member_id] = dict(event)

    # --- 결과 ---

    def results(self) -> list[CheckResult]:
        """토픽만 보고 정하는 항목 (3~10, 13). 1·2·11·12는 아래 함수가 만든다."""
        return [
            self._ops_result(),
            self._fields_result(),
            self._pii_result(),
            self._time_result(),
            self._shape_result(),
            self._key_result(),
            self._snapshot_flag_result(),
            self._duplicate_result(),
            self._live_result(),
        ]

    def _ops_result(self) -> CheckResult:
        r_count, deleted = self.ops["r"], self.ops["d"]
        unknown = {op: n for op, n in self.ops.items() if op not in params.ALLOWED_OPS}
        passed = not unknown and r_count == self.snapshot_expected
        detail = (
            f"r {r_count:,}건 (기대 {self.snapshot_expected:,}), c {self.ops['c']:,}건, "
            f"u {self.ops['u']:,}건, d {deleted:,}건"
        )
        if unknown:
            detail += f", 허용 밖 종류 {sum(unknown.values()):,}건"
        return CheckResult(3, "이벤트 종류", passed, detail)

    def _fields_result(self) -> CheckResult:
        problems = self.bad_keys.count + self.unparseable.count
        detail = f"전체 {self.total:,}건 중 필드 집합이 다른 메시지 {self.bad_keys.text()}"
        if self.key_field_problems:
            detail += " — " + ", ".join(
                f"{k} {n:,}건" for k, n in self.key_field_problems.most_common(8)
            )
        if self.unparseable.count:
            detail += f", JSON이 아닌 메시지 {self.unparseable.count:,}건"
        return CheckResult(4, "필드", problems == 0, detail)

    def _pii_result(self) -> CheckResult:
        if not self.pii_hits:
            return CheckResult(5, "PII 없음", True, f"메시지 원문 {self.total:,}건에서 0건")
        found = ", ".join(f"{name} {n:,}건" for name, n in self.pii_hits.most_common())
        return CheckResult(5, "PII 없음", False, f"원문에서 발견: {found}")

    def _time_result(self) -> CheckResult:
        problems = self.bad_time.count + self.bad_snapshot_range.count
        detail = (
            f"UTC(Z) 형식이 아닌 메시지 {self.bad_time.text()}, "
            f"r의 signup_at 범위 밖 {self.bad_snapshot_range.text()}"
        )
        return CheckResult(6, "시각", problems == 0, detail)

    def _shape_result(self) -> CheckResult:
        detail = f"값 모양이 어긋난 메시지 {self.bad_shape.text()}"
        if self.shape_fields:
            detail += " — " + ", ".join(f"{k} {n:,}건" for k, n in self.shape_fields.most_common())
        return CheckResult(7, "값 모양", self.bad_shape.count == 0, detail)

    def _key_result(self) -> CheckResult:
        return CheckResult(
            8,
            "키",
            self.key_mismatch.count == 0,
            f"키와 값의 member_id가 다른 메시지 {self.key_mismatch.text()}",
        )

    def _snapshot_flag_result(self) -> CheckResult:
        return CheckResult(
            9,
            "관리 컬럼",
            self.bad_snapshot_flag.count == 0,
            f"스냅샷 값이 어긋난 메시지 {self.bad_snapshot_flag.text()}",
        )

    def _duplicate_result(self) -> CheckResult:
        return CheckResult(
            10,
            "중복",
            self.duplicates.count == 0,
            f"같은 종류(r/c)에서 member_id가 겹친 메시지 {self.duplicates.text()}",
        )

    def _live_result(self) -> CheckResult:
        if self.live_expected is None:
            return CheckResult(
                13, "신규 가입", True, "--live-expected를 주지 않아 건너뜀", skipped=True
            )
        count = self.ops["c"]
        return CheckResult(
            13,
            "신규 가입",
            count == self.live_expected,
            f"c {count:,}건 (기대 {self.live_expected:,})",
        )


# --- DB·Connect와 대조하는 항목 ---


def check_connector(
    status: Mapping[str, Any] | None, config: Mapping[str, Any] | None
) -> CheckResult:
    """1번: 커넥터·task RUNNING, 실제 등록된 설정이 안전장치와 같다."""
    if status is None or config is None:
        return CheckResult(1, "커넥터", False, "커넥터가 등록되어 있지 않습니다")
    connector, tasks = states(status)
    problems = config_problems(config)
    detail = f"커넥터 {connector}, task {', '.join(tasks) or '없음'}"
    if problems:
        detail += f"; 등록된 설정이 안전장치와 다릅니다 ({len(problems)}건)"
    return CheckResult(1, "커넥터", is_running(status) and not problems, detail)


def check_db_side(slot_plugin: str | None, slot_active: bool, tables: Iterable[str]) -> CheckResult:
    """2번: 슬롯 member_slot(pgoutput)이 있고 활성, publication 테이블은 public.members 하나."""
    table_list = sorted(tables)
    if slot_plugin is None:
        return CheckResult(2, "DB 쪽", False, f"슬롯 {params.SLOT_NAME}이 없습니다")
    passed = slot_plugin == "pgoutput" and slot_active and table_list == [params.SOURCE_TABLE]
    detail = (
        f"슬롯 {params.SLOT_NAME}({slot_plugin}) {'활성' if slot_active else '비활성'}, "
        f"publication 테이블 {', '.join(table_list) or '없음'}"
    )
    return CheckResult(2, "DB 쪽", passed, detail)


def compare_member_ids(event_ids: Collection[str], db_ids: Collection[str]) -> CheckResult:
    """11번: 이벤트에 나온 member_id 집합 = DB member의 member_id 집합."""
    events, db = set(event_ids), set(db_ids)
    only_db, only_events = db - events, events - db
    ok = not only_db and not only_events
    detail = f"이벤트 {len(events):,}명, DB {len(db):,}명"
    if not ok:
        detail += f"; DB에만 {_ids_text(only_db)}, 이벤트에만 {_ids_text(only_events)}"
    return CheckResult(11, "DB와 일치 (전체)", ok, detail)


def _ids_text(ids: Collection[str]) -> str:
    shown = sorted(i for i in ids if _is_uuid(i))[:MAX_EXAMPLES]
    suffix = f" (예: {', '.join(shown)})" if shown else ""
    return f"{len(ids):,}명{suffix}"


def compare_sample(
    events: Mapping[str, Mapping[str, Any]], db_rows: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """12번: DB에서 고른 샘플 회원의 값이 이벤트와 같다. 시각은 같은 순간인지로 비교한다.

    db_rows[member_id]는 signup_at, created_at(timezone 있는 datetime), region_sigungu, age_band, status.
    """
    mismatched = _Tally()
    fields: Counter[str] = Counter()
    for member_id, row in db_rows.items():
        event = events.get(member_id)
        if event is None:
            mismatched.add(member_id)
            fields["이벤트 없음"] += 1
            continue
        bad = []
        for column in ("signup_at", "created_at"):
            event_time = parse_utc(event.get(column))
            if event_time is None or event_time != row[column].astimezone(UTC):
                bad.append(column)
        for column in ("region_sigungu", "age_band", "status"):
            if event.get(column) != row[column]:
                bad.append(column)
        if bad:
            mismatched.add(member_id)
            fields.update(bad)
    detail = f"샘플 {len(db_rows):,}명 중 다른 회원 {mismatched.text()}"
    if fields:
        detail += " — " + ", ".join(f"{k} {n:,}건" for k, n in fields.most_common())
    return CheckResult(12, "DB와 일치 (샘플)", mismatched.count == 0 and bool(db_rows), detail)
