"""Gold B 재처리 잡: 승인된 시간대에 Kafka에 들어온 메시지를 다시 검사해, 그 메시지들의 옛 결과만 새 결과로 바꾼다.

평소에는 적재 잡이 원장에 계속 쌓고, 재처리는 기존 결과를 고치기만 한다 (원장을 새로 만들지 않음, 2026-10-23).
설계는 docs/design/gold-b/README.md 「재실행·재처리 설계와 검증」, 「⑤ reprocess_events」.
기본값과 부르는 방법은 같은 폴더의 README.md에 있다.

run() 한 번에 하는 일
  1. 승인 범위를 UTC 1시간 폴더로 넓힌다 (끝은 포함하지 않음).
  2. 시작 전 확인: 형식 검사 규칙 버전, 안 끝난 폴더, Kafka 보관 기간. 걸리면 FAILED (다시 돌려도 소용없음).
  3. reprocess_events에 STARTED를 쓴다.
  4. 그 시간대에 Kafka에 들어온 메시지(대상 메시지)를 한 번에 다시 읽고 검사한다. 앞뒤 여유 시간은 더 읽지 않는다.
     대상 메시지마다 새 줄과, 옛 결과·새 결과가 있는 시간 폴더를 메시지로 정한다 (②④는 Kafka 시각, ①은 결제 시각).
     결제 시각 폴더는 승인 범위 밖일 수 있다 (예: 다음 날 들어온 결제 수정). 범위 밖 폴더는 결과가 바뀌는 결제가 있을 때만 고친다.
  5. (가) 검사 결과(①·④) 새 줄을 모든 폴더에 먼저 더한다. (나) 폴더마다 대상 메시지의 옛 결과를 지우고 파일 하나로 정리한 뒤
     LEDGER_REPLACED를 쓴다 (승인 범위 밖 폴더는 detail에 outside_window). ②는 (나)에서 바로 바꾼다.
     대상이 아닌 메시지의 줄은 건드리지 않는다.
  6. 도중에 실패하면 FAILED를 쓰고 예외를 다시 올린다. 끝난 폴더의 LEDGER_REPLACED는 남는다.

next_request()는 poller다. reprocess_events를 읽어 지금 돌릴 승인 요청 하나를 고른다 (source가 KAFKA·BRONZE인 것만,
승인이 가장 이른 것부터). Airflow DAG가 5분마다 부른다.

Kafka는 읽기만 한다 (임시 그룹으로 assign만 하고 처리 위치를 커밋하지 않음).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Callable, Mapping, Protocol, Sequence
import uuid

from pipelines.gold_b.ledger import (EVENT_TIME, HOUR, SCHEMAS, Checker, KafkaMessage, Store,
                                     hour_folder, hour_of, message_rows, open_store, utc_naive)
from pipelines.timestamps import parse_iso_datetime

ACTOR = "reprocess_job"   # reprocess_events.actor (판정 잡은 detect_job)
SOURCE_KAFKA = "KAFKA"
# 다시 만드는 원장. bronze_lag_snapshots는 그 시점에만 잴 수 있는 값이라 건드리지 않는다
REPLACED_TABLES = ("payment_events", "topic_messages", "malformed_events")
# (가)에서 먼저 더하는 원장: 검사 결과만. topic_messages는 옛 줄과 같은 폴더라 (나)에서 바로 바꾼다
# (먼저 더하면 판정이 세는 유입량·R4 분모와 신뢰성 점검의 "같은 위치 두 번"이 정리 전까지 늘어 보인다, 2026-10-24 주현 님)
PREADDED_TABLES = ("payment_events", "malformed_events")
DEFAULT_TOPICS = ("payments", "orders", "order-items", "members-events", "clickstream", "reviews.raw")
TIMEOUT_SEC = 30.0

# poller 기준 (설계 「⑤ reprocess_events」의 재처리 시작)
GOLD_B_SOURCES = ("KAFKA", "BRONZE")       # 이 잡이 맡는 요청의 source. SILVER는 승인 화면이 Silver DAG를 직접 부른다
APPROVAL_TTL = timedelta(minutes=60)       # 승인 뒤 이 시간 안에 시작하지 못하면 승인 만료 (승인 화면과 같은 값)
MAX_RUNS = 3                               # 한 요청을 돌리는 최대 횟수: 처음 1번 + 일시 실패 자동 재시도 2번
_RUN_STEPS = ("STARTED", "LEDGER_REPLACED", "FAILED")
_STEP_ORDER = {step: i for i, step in enumerate(
    ("REQUESTED", "APPROVED", "REJECTED", "STARTED", "LEDGER_REPLACED", "FAILED", "REDETECTED", "VERIFIED"))}


class ReprocessError(RuntimeError):
    """재처리를 끝내지 못했다. retryable이 False면 다시 돌려도 결과가 같다 (DAG는 재시도하지 않고 멈춘다)."""

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class TopicMissing(Exception):
    """Kafka에 그 토픽이 없다."""


@dataclass(frozen=True)
class Request:
    """승인된 재처리 요청. 시각은 UTC (시간대 표시가 없으면 UTC로 본다)."""

    request_id: str
    window_start: datetime
    window_end: datetime
    rule_version: str
    attempt: int = 1                      # 요청 단위 시도 번호 (승인 화면이 정함). 한 요청 안의 재실행 횟수는 STARTED의 detail.run
    parent_request_id: str | None = None


@dataclass(frozen=True)
class Options:
    topics: tuple[str, ...] = DEFAULT_TOPICS
    payments_topic: str = "payments"               # payment_events 줄의 토픽 (원장에 토픽 칸이 없음)
    margin: timedelta = timedelta(minutes=10)      # 안 끝난 폴더·보관 기간 확인의 여유 (읽는 범위는 넓히지 않음)
    retention: timedelta = timedelta(days=7)       # Kafka 보관 기간 (업무 토픽 retention.ms 7일, 2026-10-23 #86)


@dataclass(frozen=True)
class Result:
    request_id: str
    replaced: list[tuple[datetime, datetime]]      # 승인 범위에서 고친 시간 폴더 [시작, 끝)
    details: list[dict]                            # 고친 폴더마다(범위 밖 포함, 고친 순서) LEDGER_REPLACED의 detail
    outside: list[tuple[datetime, datetime]] = field(default_factory=list)   # 승인 범위 밖에서 고친 결제 시각 폴더


class KafkaSource(Protocol):
    def partitions(self, topic: str) -> list[int]: ...
    def offsets_for_time(self, topic: str, partitions: Sequence[int], at: datetime) -> dict[int, int]: ...
    def read(self, ranges: Mapping[tuple[str, int], tuple[int, int]]) -> list[KafkaMessage]: ...


# ---------- 시작 전 확인 ----------

def hour_folders(window_start: datetime, window_end: datetime) -> list[datetime]:
    """승인 범위를 덮는 1시간 폴더의 시작 시각. 끝은 포함하지 않는다 (14:40~16:20 → 14·15·16시, 15:00~16:00 → 15시)."""
    start, end = utc_naive(window_start), utc_naive(window_end)
    if end <= start:
        raise ReprocessError("승인 범위의 끝이 시작보다 늦어야 한다", retryable=False)
    hours, hour = [], hour_of(start)
    while hour < end:
        hours.append(hour)
        hour += HOUR
    return hours


def check_request(request: Request, checker: Checker, options: Options, now: datetime) -> list[datetime]:
    """교체할 시간 폴더를 돌려준다. 다시 돌려도 소용없는 문제면 ReprocessError(retryable=False)."""
    if not request.request_id:
        raise ReprocessError("request_id가 비어 있다", retryable=False)
    if checker.rule_version != request.rule_version:
        raise ReprocessError(f"형식 검사 규칙 버전({checker.rule_version})이 승인된 버전"
                             f"({request.rule_version})과 다르다", retryable=False)
    hours = hour_folders(request.window_start, request.window_end)
    if hours[-1] + HOUR + options.margin > now:
        raise ReprocessError("아직 끝나지 않은 시간 폴더가 있다 (폴더 끝 + 여유 시간이 지난 뒤 다시 승인)",
                             retryable=False)
    if hours[0] - options.margin < now - options.retention:
        raise ReprocessError("Kafka 보관 기간 밖이라 원본이 없다 (Bronze 재처리는 아직 없음)", retryable=False)
    return hours


# ---------- 다시 읽기와 고칠 곳 ----------

def read_ranges(source: KafkaSource, topics: Sequence[str], read_from: datetime,
                read_to: datetime) -> tuple[dict[tuple[str, int], tuple[int, int]], list[str]]:
    """토픽·파티션마다 다시 읽을 위치 [시작, 끝)와 Kafka에 없는 토픽."""
    ranges: dict[tuple[str, int], tuple[int, int]] = {}
    missing: list[str] = []
    for topic in topics:
        try:
            partitions = source.partitions(topic)
        except TopicMissing:
            missing.append(topic)
            continue
        starts = source.offsets_for_time(topic, partitions, read_from)
        ends = source.offsets_for_time(topic, partitions, read_to)
        for partition in partitions:
            ranges[(topic, partition)] = (starts[partition], max(starts[partition], ends[partition]))
    return ranges, missing


@dataclass
class Plan:
    """재처리 한 번이 고칠 것: 대상 메시지 위치, 새 줄, 옛 결과·새 결과가 있는 시간 폴더."""

    targets: set[tuple[str, int, int]] = field(default_factory=set)        # (토픽, 파티션, offset)
    new_rows: dict[tuple[str, datetime], list[dict]] = field(default_factory=lambda: defaultdict(list))
    tables: dict[datetime, set[str]] = field(default_factory=lambda: defaultdict(set))   # 시간 폴더 → 고칠 원장
    messages: dict[datetime, int] = field(default_factory=lambda: defaultdict(int))      # 시간 폴더 → 대상 메시지 수
    missing_topics: list[str] = field(default_factory=list)
    paid: dict[datetime, set[tuple[str, int, int]]] = field(default_factory=lambda: defaultdict(set))
    """결제 시각 폴더 → 그 폴더에 ① 줄이 있거나 생길 대상 결제 위치"""
    outside_targets: dict[datetime, set[tuple[str, int, int]]] = field(default_factory=dict)
    """승인 범위 밖 결제 시각 폴더 → 결과가 바뀌어서 고칠 결제 위치 (narrow_outside가 정함)"""


def _completed_hour(message: KafkaMessage) -> datetime | None:
    """결제 메시지 값의 completed_at 시간 폴더 (그 메시지의 옛 ① 줄이 있을 곳). 읽을 수 없으면 None."""
    try:
        value = json.loads(message.value)
        return hour_of(parse_iso_datetime(str(value["completed_at"])))
    except (TypeError, ValueError, KeyError):
        return None


def plan_replacement(messages: Sequence[KafkaMessage], checker: Checker, rule_version: str, loaded_at: datetime,
                     payments_topic: str, missing_topics: Sequence[str] = ()) -> Plan:
    """대상 메시지마다 새 줄을 만들고, 옛 결과와 새 결과가 있는 시간 폴더를 모은다.
    원장을 뒤지지 않고 메시지로 정한다: ②④는 Kafka 시각 폴더, ①은 결제 시각(completed_at) 폴더.
    새 결과가 오류여도 옛 ① 줄은 결제 시각 폴더에서 지운다 (통과했던 결제가 새 규칙에서 오류가 된 경우)."""
    plan = Plan(missing_topics=list(missing_topics))
    for message in messages:
        plan.targets.add(message.position)
        kafka_hour = hour_of(message.timestamp)
        folders = {("topic_messages", kafka_hour), ("malformed_events", kafka_hour)}
        if message.topic == payments_topic and (paid_hour := _completed_hour(message)) is not None:
            folders.add(("payment_events", paid_hour))
            plan.paid[paid_hour].add(message.position)
        for table, rows in message_rows(message, checker(message), rule_version, loaded_at).items():
            for row in rows:
                hour = hour_of(row[EVENT_TIME[table]])
                plan.new_rows[(table, hour)].append(row)
                folders.add((table, hour))
        for table, hour in folders:
            plan.tables[hour].add(table)
        for hour in {hour for _, hour in folders}:
            plan.messages[hour] += 1
    return plan


def _same_result(old: Mapping, new: Mapping) -> bool:
    """같은 검사 결과의 ① 줄인가 (쌓은 시각과 규칙 버전만 다를 수 있다)."""
    return all(old[name] == new[name] for name in SCHEMAS["payment_events"].names
               if name not in ("loaded_at", "rule_version"))


def narrow_outside(plan: Plan, store: Store, window: set[datetime], payments_topic: str) -> None:
    """승인 범위 밖 결제 시각 폴더는 결과가 바뀌는 결제가 있을 때만 고친다 (2026-10-24, 주현 님).
    그 폴더도 재판정되므로 꼭 필요한 만큼만 고친다. 바뀌는 결제는 두 가지다:
    새 결과가 통과인데 같은 ① 줄이 그 폴더에 없음 (복구), 새 결과가 오류인데 옛 ① 줄이 있음 (보류로 바뀜).
    같은 통과 줄이 이미 있으면(예: 시간 경계에 걸린 결제를 같은 결과로 다시 검사) 그 결제의 줄을 그대로 둔다."""
    for hour in sorted(h for h in plan.paid if h not in window):
        positions = plan.paid[hour]
        new = {(payments_topic, row["kafka_partition"], row["kafka_offset"]): row
               for row in plan.new_rows.get(("payment_events", hour), [])}
        old: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
        for path in store.files(hour_folder("payment_events", hour)):
            for row in store.read(path, "payment_events"):
                position = (payments_topic, row["kafka_partition"], row["kafka_offset"])
                if position in positions:
                    old[position].append(row)
        changed = {position for position in positions
                   if (position in new and not any(_same_result(row, new[position]) for row in old[position]))
                   or (position not in new and old[position])}
        plan.outside_targets[hour] = changed
        plan.messages[hour] -= len(positions - changed)
        rows = [new[position] for position in sorted(changed) if position in new]
        if rows:
            plan.new_rows[("payment_events", hour)] = rows
        else:
            plan.new_rows.pop(("payment_events", hour), None)
        if not changed:
            plan.tables[hour].discard("payment_events")
            if not plan.tables[hour]:
                del plan.tables[hour]
                plan.messages.pop(hour, None)


# ---------- 폴더 하나 정리 ----------

def _rebuilt(table: str, row: Mapping, targets: set[tuple[str, int, int]], rule_version: str,
             payments_topic: str) -> bool:
    """새 결과로 바뀌는 대상 메시지의 옛 줄인가. 대상이 아닌 메시지의 줄은 그대로 둔다.
    malformed_events는 다른 규칙 버전의 줄을 남긴다 (예전 판정 이력)."""
    if table == "malformed_events" and row["rule_version"] != rule_version:
        return False
    topic = payments_topic if table == "payment_events" else row["topic"]
    return (topic, row["kafka_partition"], row["kafka_offset"]) in targets


_SORT_COLUMNS = {
    "payment_events": ("kafka_partition", "kafka_offset"),
    "topic_messages": ("topic", "kafka_partition", "kafka_offset"),
    "malformed_events": ("rule_version", "topic", "kafka_partition", "kafka_offset", "field"),
}


def _sort_key(table: str) -> Callable[[Mapping], tuple]:
    columns = _SORT_COLUMNS[table]
    return lambda row: tuple((row[c] is None, row[c] if row[c] is not None else 0) for c in columns)


def replace_table(store: Store, table: str, hour: datetime, new_rows: Sequence[dict],
                  targets: set[tuple[str, int, int]], rule_version: str, payments_topic: str,
                  stamp: str) -> tuple[int, int]:
    """시간 폴더 하나의 원장 하나에서 대상 메시지의 옛 줄을 새 줄로 바꾸고 파일 하나로 정리한다.
    (새 줄 수, 남긴 옛 줄 수). (가)에서 먼저 더한 새 줄 파일도 대상 메시지의 줄이라 여기서 다시 정리된다."""
    folder = hour_folder(table, hour)
    old_files = store.files(folder)
    kept, seen = [], set()
    for path in old_files:
        for row in store.read(path, table):
            if _rebuilt(table, row, targets, rule_version, payments_topic):
                continue
            key = tuple(row[name] for name in SCHEMAS[table].names)
            if key in seen:   # 앞선 시도가 새 파일을 쓰고 옛 파일을 못 지웠으면 같은 줄이 두 파일에 있다
                continue
            seen.add(key)
            kept.append(row)
    rows = sorted([*kept, *new_rows], key=_sort_key(table))
    if rows:
        store.write(f"{folder}/part-reprocess-{stamp}-{uuid.uuid4().hex[:8]}.parquet", table, rows)
    # 새 파일을 다 쓴 뒤에 옛 파일을 지운다. 그 사이 적재 잡이 새로 쓴 파일은 목록에 없어서 남는다
    store.delete(old_files)
    return len(new_rows), len(kept)


def add_new_rows(store: Store, plan: Plan, stamp: str) -> None:
    """(가) 검사 결과(①·④)의 새 줄을 폴더마다 파일로 먼저 더한다. 이 뒤에 멈춰도 결과가 사라지지 않는다
    (같은 위치에 옛 결과와 새 결과가 함께 있으면 뷰 payment_states가 더 늦게 쌓인 새 결과를 고른다)."""
    for (table, hour), rows in sorted(plan.new_rows.items(), key=lambda item: (item[0][1], item[0][0])):
        if rows and table in PREADDED_TABLES:
            store.write(f"{hour_folder(table, hour)}/part-reprocess-{stamp}-new-{uuid.uuid4().hex[:8]}.parquet",
                        table, rows)


def tidy_hour(store: Store, plan: Plan, hour: datetime, inside: bool, rule_version: str, payments_topic: str,
              stamp: str) -> dict:
    """(나) 시간 폴더 하나에서 대상 메시지의 옛 결과를 지우고 정리한다. LEDGER_REPLACED의 detail을 돌려준다.
    승인 범위 폴더는 원장 3개를 모두 정리하고, 범위 밖 폴더는 대상 메시지가 있는 원장만 정리한다."""
    tables = REPLACED_TABLES if inside else tuple(t for t in REPLACED_TABLES if t in plan.tables.get(hour, set()))
    detail: dict = {"messages": plan.messages.get(hour, 0), "written": {}, "kept": {}}
    for table in tables:
        # 범위 밖 결제 시각 폴더의 ①은 결과가 바뀌는 결제만 고친다 (narrow_outside)
        targets = plan.outside_targets.get(hour, plan.targets) if table == "payment_events" and not inside \
            else plan.targets
        written, kept = replace_table(store, table, hour, plan.new_rows.get((table, hour), []), targets,
                                      rule_version, payments_topic, stamp)
        detail["written"][table] = written
        detail["kept"][table] = kept
    if inside and plan.missing_topics:
        detail["missing_topics"] = plan.missing_topics
    if not inside:
        detail["outside_window"] = True
    return detail


# ---------- reprocess_events 기록 ----------

class _Events:
    def __init__(self, store: Store, request: Request, clock: Callable[[], datetime]):
        self._store, self._request, self._clock = store, request, clock

    def write(self, step: str, window: tuple[datetime, datetime], source: str | None,
              detail: Mapping | None) -> None:
        at = utc_naive(self._clock())
        r = self._request
        row = {"request_id": r.request_id, "step": step, "at": at, "actor": ACTOR, "reason": None,
               "window_start": window[0], "window_end": window[1], "rule_version": r.rule_version,
               "source": source, "attempt": r.attempt, "parent_request_id": r.parent_request_id,
               "detail": None if detail is None else json.dumps(detail, ensure_ascii=False, sort_keys=True)}
        name = f"part-{at:%Y%m%dT%H%M%S%fZ}-{step.lower()}-{uuid.uuid4().hex[:8]}.parquet"
        self._store.write(f"reprocess_events/{name}", "reprocess_events", [row])


def _error_label(exc: BaseException) -> str:
    """실패 이유. 이 잡이 만든 오류만 문장을 쓰고, 나머지는 종류만 쓴다 (Kafka·S3 오류 문장에는 주소·버킷이 들어 있을 수 있음)."""
    if isinstance(exc, ReprocessError):
        return str(exc)
    if exc.args and hasattr(exc.args[0], "name"):   # confluent_kafka.KafkaException(KafkaError)
        try:
            return f"{type(exc).__name__}({exc.args[0].name()})"
        except Exception:
            pass
    return type(exc).__name__


def _log(message: str) -> None:
    print(message, flush=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- 실행 ----------

def run(request: Request, *, source: KafkaSource, store: Store, checker: Checker,
        options: Options = Options(), now: Callable[[], datetime] = _utc_now,
        log: Callable[[str], None] = _log, run_number: int = 1) -> Result:
    """재처리 한 번. 성공하면 교체한 시간 폴더를 돌려주고, 실패하면 FAILED를 쓴 뒤 예외를 다시 올린다.
    run_number는 이 요청을 몇 번째로 돌리는지다 (poller가 정함, STARTED의 detail.run)."""
    events = _Events(store, request, now)
    approved = (utc_naive(request.window_start), utc_naive(request.window_end))

    def fail(window: tuple[datetime, datetime], source_name: str | None, exc: BaseException, done: int) -> None:
        detail = {"error": _error_label(exc),
                  "retryable": exc.retryable if isinstance(exc, ReprocessError) else True}
        if done:
            detail["replaced_folders"] = done
        try:
            events.write("FAILED", window, source_name, detail)
        except Exception as write_error:   # 기록을 못 써도 원래 오류를 올린다
            log(f"재처리 {request.request_id}: FAILED 기록을 쓰지 못함 ({_error_label(write_error)})")
        log(f"재처리 {request.request_id} 실패: {detail['error']}")

    try:
        hours = check_request(request, checker, options, utc_naive(now()))
    except ReprocessError as exc:
        fail(approved, None, exc, 0)
        raise

    window = set(hours)
    folders = list(hours)                          # 고칠 시간 폴더 (계획을 세운 뒤 범위 밖 결제 시각 폴더가 더해짐)
    replaced: list[tuple[datetime, datetime]] = []
    outside: list[tuple[datetime, datetime]] = []
    details: list[dict] = []
    current = hours[0]
    try:
        events.write("STARTED", approved, SOURCE_KAFKA,
                     {"folders": [f"{h:%Y-%m-%dT%H:00}" for h in hours], "run": run_number})
        log(f"재처리 {request.request_id} 시작: 시간 폴더 {len(hours)}개")
        loaded_at = utc_naive(now())
        ranges, missing = read_ranges(source, options.topics, hours[0], hours[-1] + HOUR)
        plan = plan_replacement(source.read(ranges), checker, request.rule_version, loaded_at,
                                options.payments_topic, missing)
        narrow_outside(plan, store, window, options.payments_topic)
        folders = sorted(window | set(plan.tables))
        current = folders[0]
        stamp = f"{loaded_at:%Y%m%dT%H%M%SZ}"
        add_new_rows(store, plan, stamp)
        for hour in folders:   # 시간 순서. 결제 시각 폴더는 보통 Kafka 시각 폴더보다 앞이다
            current = hour
            inside = hour in window
            detail = tidy_hour(store, plan, hour, inside, request.rule_version, options.payments_topic, stamp)
            # 폴더 정리가 다 끝난 뒤에 쓴다. 판정 잡은 이 줄을 보고 그 시간대를 재판정한다 (범위 밖 결제 시각 폴더도)
            events.write("LEDGER_REPLACED", (hour, hour + HOUR), SOURCE_KAFKA, detail)
            (replaced if inside else outside).append((hour, hour + HOUR))
            details.append(detail)
            log(f"재처리 {request.request_id}: {hour:%Y-%m-%d %H}시 폴더 정리{'' if inside else ' (승인 범위 밖)'} "
                f"(대상 메시지 {detail['messages']}, 새 줄 {sum(detail['written'].values())}, "
                f"남긴 줄 {sum(detail['kept'].values())})")
    except Exception as exc:
        # 남은 폴더 범위를 FAILED에 적는다. 끝난 폴더는 LEDGER_REPLACED가 있어 재판정된다
        fail((current, folders[-1] + HOUR), SOURCE_KAFKA, exc, len(replaced) + len(outside))
        raise
    return Result(request.request_id, replaced, details, outside)


# ---------- 다음에 돌릴 요청 고르기 (poller) ----------

@dataclass(frozen=True)
class Pending:
    request: Request
    run_number: int      # 이 요청을 몇 번째로 돌리는지 (1부터)


def read_events(store: Store) -> list[dict]:
    """reprocess_events의 줄 전부. 승인 화면·판정 잡이 Athena INSERT로 쓴 파일은 이름에 확장자가 없을 수 있어서 다 읽는다."""
    rows: list[dict] = []
    for path in store.files("reprocess_events", any_name=True):
        rows.extend(store.read(path, "reprocess_events"))
    return rows


def _detail(row: Mapping) -> dict:
    try:
        value = json.loads(row.get("detail") or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _finished(runs: Sequence[Mapping], approved: Mapping) -> bool:
    """마지막 STARTED 뒤에 승인 범위의 시간 폴더가 모두 LEDGER_REPLACED로 끝났는가."""
    try:
        wanted = set(hour_folders(approved["window_start"], approved["window_end"]))
    except ReprocessError:
        return False
    starts = [i for i, row in enumerate(runs) if row["step"] == "STARTED"]
    after = runs[starts[-1] + 1:] if starts else runs
    replaced = {utc_naive(row["window_start"]) for row in after
                if row["step"] == "LEDGER_REPLACED" and row.get("window_start") is not None}
    return wanted <= replaced


def next_request(rows: Sequence[Mapping], now: datetime, *, sources: Sequence[str] = GOLD_B_SOURCES,
                 ttl: timedelta = APPROVAL_TTL, max_runs: int = MAX_RUNS) -> Pending | None:
    """poller: 지금 돌릴 요청 하나 (승인이 가장 이른 것부터, 한 번에 하나). 없으면 None.

    - APPROVED 줄의 source가 sources에 있는 요청만 맡는다.
    - 아직 시작하지 않았으면 승인 뒤 ttl 안일 때만 돌린다 (지나면 승인 만료).
    - 시작했으면 다시 돌려도 되는 실패(FAILED의 retryable)나 중간에 멈춘 실행(마지막 STARTED 뒤 폴더가 다 끝나지 않음)만,
      돌린 횟수(STARTED 수)가 max_runs보다 적을 때 다시 돌린다.
    """
    now = utc_naive(now)
    by_request: dict[str, list[Mapping]] = defaultdict(list)
    for row in rows:
        if row.get("request_id") and row.get("at") is not None:
            by_request[row["request_id"]].append(row)
    candidates = []
    for request_id, events in by_request.items():
        events = sorted(events, key=lambda r: (utc_naive(r["at"]), _STEP_ORDER.get(r["step"], len(_STEP_ORDER))))
        approvals = [row for row in events if row["step"] == "APPROVED"]
        if not approvals or any(row["step"] == "REJECTED" for row in events):
            continue
        approved = approvals[-1]
        if approved.get("source") not in sources:
            continue
        if approved.get("window_start") is None or approved.get("window_end") is None:
            continue
        runs = [row for row in events if row["step"] in _RUN_STEPS]
        run_count = sum(row["step"] == "STARTED" for row in runs)
        if not runs:
            if now - utc_naive(approved["at"]) > ttl:
                continue                                   # 승인 만료
        elif runs[-1]["step"] == "FAILED":
            if _detail(runs[-1]).get("retryable") is not True or run_count >= max_runs:
                continue                                   # 다시 돌려도 소용없거나 이미 다 돌림
        elif _finished(runs, approved) or run_count >= max_runs:
            continue                                       # 끝났거나 이미 다 돌림
        candidates.append((utc_naive(approved["at"]), request_id, approved, run_count))
    if not candidates:
        return None
    _, request_id, approved, run_count = min(candidates, key=lambda c: (c[0], c[1]))
    request = Request(request_id=request_id, window_start=utc_naive(approved["window_start"]),
                      window_end=utc_naive(approved["window_end"]), rule_version=approved.get("rule_version") or "",
                      attempt=approved.get("attempt") or 1, parent_request_id=approved.get("parent_request_id"))
    return Pending(request, run_count + 1)


# ---------- Kafka 읽기 ----------

def _quiet_logger() -> logging.Logger:
    """librdkafka 내부 로그를 버리는 로거. 그 로그에는 브로커 주소가 들어 있다 (수집기·시뮬레이터와 같은 방식)."""
    logger = logging.getLogger("gold_b.reprocess.librdkafka")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class KafkaReader:
    """시각으로 위치를 찾고 [시작, 끝) 위치의 메시지를 읽는다.

    config는 confluent-kafka 설정이다 (bootstrap.servers, security.protocol, ssl.* 등. 수집기와 같은 환경변수로 만든다).
    임시 그룹으로 assign만 하고 커밋하지 않는다.
    """

    def __init__(self, config: Mapping[str, object], timeout: float = TIMEOUT_SEC):
        from confluent_kafka import Consumer
        from confluent_kafka.admin import AdminClient

        base = {"logger": _quiet_logger(), **config}
        self._timeout = timeout
        # 토픽 정보를 물을 때 없는 토픽이 자동으로 생기지 않게 한다
        self._admin = AdminClient({**base, "allow.auto.create.topics": False})
        self._consumer = Consumer({
            **base,
            "group.id": f"gold-b-reprocess-{uuid.uuid4().hex}",
            "enable.auto.commit": False,
            "enable.partition.eof": True,
            "allow.auto.create.topics": False,
            # 읽으려던 위치가 그 사이 보관 기간으로 지워졌으면 남은 것부터 읽는다 (못 읽은 메시지의 옛 줄은 남는다)
            "auto.offset.reset": "earliest",
        })

    def partitions(self, topic: str) -> list[int]:
        metadata = self._admin.list_topics(topic=topic, timeout=self._timeout).topics.get(topic)
        if metadata is None or metadata.error is not None or not metadata.partitions:
            raise TopicMissing(topic)
        return sorted(metadata.partitions)

    def offsets_for_time(self, topic: str, partitions: Sequence[int], at: datetime) -> dict[int, int]:
        """파티션마다 Kafka 시각이 at 이상인 첫 위치. 그런 메시지가 없으면 끝 위치."""
        from confluent_kafka import TopicPartition

        millis = int(utc_naive(at).replace(tzinfo=timezone.utc).timestamp() * 1000)
        found = self._consumer.offsets_for_times([TopicPartition(topic, p, millis) for p in partitions],
                                                 timeout=self._timeout)
        offsets: dict[int, int] = {}
        for tp in found:
            if tp.error is not None:
                raise ReprocessError(f"Kafka 위치 조회 오류 {tp.error.name()}", retryable=True)
            if tp.offset >= 0:
                offsets[tp.partition] = tp.offset
                continue
            watermarks = self._consumer.get_watermark_offsets(TopicPartition(topic, tp.partition),
                                                              timeout=self._timeout)
            if watermarks is None:
                raise ReprocessError("Kafka 끝 위치를 읽지 못했다", retryable=True)
            offsets[tp.partition] = watermarks[1]
        return offsets

    def read(self, ranges: Mapping[tuple[str, int], tuple[int, int]]) -> list[KafkaMessage]:
        from confluent_kafka import KafkaError, TopicPartition

        wanted = {key: span for key, span in ranges.items() if span[0] < span[1]}
        messages: list[KafkaMessage] = []
        if not wanted:
            return messages
        self._consumer.assign([TopicPartition(t, p, start) for (t, p), (start, _) in wanted.items()])
        # 앞선 read()에서 다 읽고 멈춰 둔 파티션은 다시 assign해도 멈춘 채라서 푼다 (같은 연결로 폴더를 차례로 읽을 때)
        self._consumer.resume([TopicPartition(t, p) for (t, p) in wanted])
        remaining = set(wanted)
        deadline = time.monotonic() + self._timeout

        def done(key: tuple[str, int]) -> None:
            remaining.discard(key)
            self._consumer.pause([TopicPartition(*key)])

        try:
            while remaining:
                if time.monotonic() > deadline:
                    raise ReprocessError("Kafka에서 시간 안에 다 읽지 못했다", retryable=True)
                message = self._consumer.poll(1.0)
                if message is None:
                    continue
                key = (message.topic(), message.partition())
                error = message.error()
                if error is not None:
                    if error.code() == KafkaError._PARTITION_EOF:   # 끝 위치까지 읽음
                        if key in remaining:
                            done(key)
                        continue
                    raise ReprocessError(f"Kafka 읽기 오류 {error.name()}", retryable=True)
                if key not in remaining:
                    continue
                end = wanted[key][1]
                if message.offset() >= end:
                    done(key)
                    continue
                messages.append(_to_message(message))
                deadline = time.monotonic() + self._timeout   # 읽는 동안에는 계속 기다린다
                if message.offset() >= end - 1:
                    done(key)
        finally:
            self._consumer.unassign()
        return messages

    def close(self) -> None:
        self._consumer.close()


def _to_message(message) -> KafkaMessage:
    from confluent_kafka import TIMESTAMP_NOT_AVAILABLE

    kind, millis = message.timestamp()
    if kind == TIMESTAMP_NOT_AVAILABLE or millis < 0:
        raise ReprocessError("Kafka 메시지에 시각이 없다", retryable=False)
    return KafkaMessage(topic=message.topic(), partition=message.partition(), offset=message.offset(),
                        timestamp=datetime.fromtimestamp(millis / 1000, tz=timezone.utc),
                        value=message.value(), key=message.key())


# ---------- 실행 입구 ----------

ENV_LEDGER_ROOT = "GOLD_B_LEDGER_ROOT"    # s3://<버킷>/gold_b 또는 로컬 폴더 (필수)
ENV_RULES_PATH = "GOLD_B_RULES_PATH"      # 형식 규칙표 경로 (생략하면 저장소의 docs/contracts/format_rules.yaml)


def kafka_config_from_env(env: Mapping[str, str]) -> dict[str, object]:
    """수집기와 같은 KAFKA_* 환경변수로 confluent-kafka 설정을 만든다. 주소는 로그에 남기지 않는다."""
    bootstrap = (env.get("KAFKA_BOOTSTRAP") or "").strip()
    if not bootstrap:
        raise ReprocessError("KAFKA_BOOTSTRAP이 없다", retryable=False)
    protocol = (env.get("KAFKA_SECURITY_PROTOCOL") or "PLAINTEXT").strip().upper()
    if protocol not in ("PLAINTEXT", "SSL"):
        raise ReprocessError("KAFKA_SECURITY_PROTOCOL은 PLAINTEXT, SSL 중 하나여야 한다", retryable=False)
    config: dict[str, object] = {"bootstrap.servers": bootstrap, "security.protocol": protocol}
    for key, name in (("KAFKA_SSL_CA_FILE", "ssl.ca.location"), ("KAFKA_SSL_CERT_FILE", "ssl.certificate.location"),
                      ("KAFKA_SSL_KEY_FILE", "ssl.key.location"), ("KAFKA_ADDRESS_FAMILY", "broker.address.family")):
        if env.get(key):
            config[name] = env[key]
    return config


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None,
         now: Callable[[], datetime] = _utc_now, log: Callable[[str], None] = _log) -> int:
    """poller로 승인된 요청 하나를 골라 돌린다. Airflow DAG가 5분마다 부른다 (한 번에 하나).

    할 일이 없거나 성공하면 0, 실패하면 1이다. 다시 돌릴지는 다음 번에 poller가 reprocess_events를 보고 정한다.
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="python -m pipelines.gold_b.jobs.reprocess",
                                     description="Gold B 재처리: 승인된 요청 하나를 골라 원장 ①②④를 교체한다")
    parser.add_argument("--dry-run", action="store_true", help="고른 요청만 알려 주고 돌리지 않는다")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    root = (env.get(ENV_LEDGER_ROOT) or "").strip()
    if not root:
        log(f"{ENV_LEDGER_ROOT}가 없다")
        return 1
    store = open_store(root)
    pending = next_request(read_events(store), now())
    if pending is None:
        log("돌릴 재처리 요청이 없다")
        return 0
    request = pending.request
    log(f"재처리 {request.request_id}: {request.window_start:%Y-%m-%d %H:%M}~{request.window_end:%Y-%m-%d %H:%M} UTC, "
        f"{pending.run_number}번째 실행")
    if args.dry_run:
        return 0
    from pipelines.gold_b.format_check import FormatChecker   # 규칙표와 지문 함수는 돌릴 때만 읽는다

    try:
        checker = FormatChecker(rules_path=env.get(ENV_RULES_PATH) or None)
        reader = KafkaReader(kafka_config_from_env(env))
    except Exception as exc:   # 실행 환경 문제라 요청을 실패로 남기지 않는다 (다음 번에 다시 고름)
        log(f"재처리 {request.request_id}: 준비 실패 ({_error_label(exc)})")
        return 1
    try:
        run(request, source=reader, store=store, checker=checker, now=now, log=log,
            run_number=pending.run_number)
    except Exception:   # run()이 FAILED를 쓰고 이유를 로그에 남겼다
        return 1
    finally:
        reader.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
