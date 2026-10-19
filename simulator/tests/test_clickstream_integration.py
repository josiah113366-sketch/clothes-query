"""클릭 발행 통합 테스트: 로컬 Kafka에 임시 토픽을 만들어 쓰고 지운다 (clickstream 토픽은 건드리지 않는다)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sim.behavior.kafka_sink import KafkaClickSink
from sim.behavior.model import ClickEvent
from sim.behavior.sink import click_record
from sim.clickstream import topic as kafka_topic
from sim.clickstream.topic import TopicError
from sim.clickstream.verify import verify
from sim.common.config import load_config
from sim.common.kafka import CLICK_TOPIC_PARTITIONS, load_kafka_settings

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 19, 6, 0, 0, tzinfo=UTC)


@pytest.fixture
def temp_topic():
    load_config(require_database=False)
    settings = load_kafka_settings()
    if not settings.is_local:
        pytest.skip("로컬 Kafka가 아니라 건너뜁니다")
    try:
        kafka_topic.describe(settings, "clickstream")
    except TopicError:
        pytest.skip("로컬 Kafka에 닿지 않습니다 (docker compose --profile cdc up -d kafka)")
    name = f"test-clickstream-{uuid.uuid4().hex[:8]}"
    kafka_topic.create(settings, name, CLICK_TOPIC_PARTITIONS)
    try:
        yield settings, name
    finally:
        kafka_topic.delete(settings, name)


def make_events(sessions: int, per_session: int) -> list[ClickEvent]:
    events = []
    for s in range(sessions):
        session = str(uuid.uuid4())
        for i in range(per_session):
            event_type = "cart_add" if i == per_session - 1 else "view"
            events.append(
                ClickEvent(
                    str(uuid.uuid4()),
                    event_type,
                    str(uuid.uuid4()),
                    f"{s:010d}",
                    T0 + timedelta(seconds=s + i * 7),
                    session,
                )
            )
    # 세션끼리 섞되 세션 안의 순서는 유지한다 (실제 방문처럼)
    return sorted(events, key=lambda e: e.event_time)


def test_publish_and_read_back(temp_topic) -> None:
    settings, name = temp_topic
    events = make_events(sessions=40, per_session=5)
    sink = KafkaClickSink(settings, topic=name)
    sink.check_ready()
    for event in events:
        sink.publish(event)
    sink.close()
    assert sink.stats.sent == len(events) and sink.stats.failed == 0

    info = kafka_topic.describe(settings, name)
    assert info is not None and info.partitions == CLICK_TOPIC_PARTITIONS
    offsets = kafka_topic.offsets(settings, name, info.partitions)
    assert sum(high - low for low, high in offsets.values()) == len(events)

    messages = list(kafka_topic.read_all(settings, name, offsets))
    assert len(messages) == len(events)
    expected = {e.event_id: e for e in events}
    by_session: dict[str, list[str]] = {}
    partitions: dict[str, set[int]] = {}
    for message in sorted(messages, key=lambda m: (m.partition, m.offset)):
        value = json.loads(message.value)
        event = expected[value["event_id"]]
        assert value == click_record(event)
        assert message.key == event.session_id.encode()
        by_session.setdefault(event.session_id, []).append(event.event_id)
        partitions.setdefault(event.session_id, set()).add(message.partition)
    for session, ids in by_session.items():
        assert ids == [e.event_id for e in events if e.session_id == session]
        assert len(partitions[session]) == 1

    report = verify(kafka_topic.read_all(settings, name, offsets))
    assert report.total == len(events) and report.passed


def test_check_ready_does_not_create_missing_topic(temp_topic) -> None:
    settings, _ = temp_topic
    missing = f"test-missing-{uuid.uuid4().hex[:8]}"
    sink = KafkaClickSink(settings, topic=missing)
    with pytest.raises(Exception, match="없습니다"):
        sink.check_ready()
    sink.close()
    assert kafka_topic.describe(settings, missing) is None
