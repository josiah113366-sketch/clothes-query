"""clickstream 메시지 검증 (Kafka 없이 도는 순수 로직).

메시지를 하나씩 받아 세기만 하고 내용은 남기지 않는다. 틀린 메시지는 파티션·offset만 기록한다.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sim.clickstream.topic import ClickMessage

FIELDS = ("event_id", "event_type", "member_id", "article_id", "event_time", "session_id")
EVENT_TYPES = ("view", "cart_add")
MAX_LOCATIONS = 5

CHECKS = (
    ("fields", "JSON이고 6개 필드가 있다"),
    ("event_type", "event_type이 view 또는 cart_add"),
    ("key", "메시지 키 = session_id"),
    ("one_partition", "같은 session_id는 한 파티션에만 있다"),
    ("unique_event_id", "event_id 중복 없음"),
    ("time_order", "같은 파티션·세션 안에서 event_time이 줄어들지 않는다"),
)


@dataclass
class CheckResult:
    failed: int = 0
    locations: list[str] = field(default_factory=list)

    def fail(self, location: str) -> None:
        self.failed += 1
        if len(self.locations) < MAX_LOCATIONS:
            self.locations.append(location)

    @property
    def passed(self) -> bool:
        return self.failed == 0


@dataclass
class VerifyReport:
    total: int
    results: dict[str, CheckResult]

    @property
    def empty(self) -> bool:
        return self.total == 0

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results.values())


def verify(messages: Iterable[ClickMessage]) -> VerifyReport:
    results = {name: CheckResult() for name, _ in CHECKS}
    session_partitions: dict[str, set[int]] = {}
    event_ids: set[str] = set()
    last_time: dict[tuple[int, str], datetime] = {}
    total = 0

    for message in messages:
        total += 1
        where = f"p{message.partition}@{message.offset}"
        record = _parse(message.value)
        if record is None:
            results["fields"].fail(where)
            continue
        if record["event_type"] not in EVENT_TYPES:
            results["event_type"].fail(where)
        session_id = record["session_id"]
        if message.key is None or message.key.decode("utf-8", "replace") != session_id:
            results["key"].fail(where)
        partitions = session_partitions.setdefault(session_id, set())
        if partitions and message.partition not in partitions:
            results["one_partition"].fail(where)
        partitions.add(message.partition)
        if record["event_id"] in event_ids:
            results["unique_event_id"].fail(where)
        event_ids.add(record["event_id"])
        try:
            event_time = datetime.fromisoformat(record["event_time"])
        except ValueError:
            results["time_order"].fail(where)
            continue
        if event_time.tzinfo is None:
            results["time_order"].fail(where)
            continue
        slot = (message.partition, session_id)
        previous = last_time.get(slot)
        if previous is not None and event_time < previous:
            results["time_order"].fail(where)
        else:
            last_time[slot] = event_time

    return VerifyReport(total=total, results=results)


def _parse(value: bytes | None) -> dict[str, str] | None:
    if value is None:
        return None
    try:
        record = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if any(not isinstance(record.get(name), str) for name in FIELDS):
        return None
    return record
