import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from confluent_kafka import KafkaError, KafkaException

from sim.behavior.kafka_sink import ClickSinkError, KafkaClickSink
from sim.behavior.model import ClickEvent
from sim.behavior.sink import click_record
from sim.common.kafka import KafkaSettings

SETTINGS = KafkaSettings(bootstrap="b-1.kafka.internal:9093")
VIEW = ClickEvent(
    "e-1", "view", "m-1", "0108775015", datetime(2026, 10, 12, 0, 30, 0, tzinfo=UTC), "s-1"
)
CART = ClickEvent(
    "e-2", "cart_add", "m-1", "0108775015", datetime(2026, 10, 12, 0, 31, 0, tzinfo=UTC), "s-1"
)


@dataclass
class FakeTopic:
    partitions: dict = field(default_factory=lambda: {0: None, 1: None, 2: None})
    error: object = None


@dataclass
class FakeMetadata:
    topics: dict


class FakeProducer:
    """produce를 쌓아 두고 poll/flush 때 전송 결과 콜백을 부른다."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.produced: list[tuple[str, bytes, bytes]] = []
        self.pending: list = []
        self.buffer_errors = 0
        self.fail_with: KafkaError | None = None
        self.flushes = 0
        self.metadata: FakeMetadata | Exception = FakeMetadata({"clickstream": FakeTopic()})
        self.calls: list[str] = []

    def produce(self, topic: str, value: bytes, key: bytes, on_delivery) -> None:
        self.calls.append("produce")
        if self.buffer_errors:
            self.buffer_errors -= 1
            raise BufferError("queue full")
        self.produced.append((topic, key, value))
        self.pending.append(on_delivery)

    def poll(self, timeout: float) -> int:
        self.calls.append("poll")
        done, self.pending = self.pending, []
        for callback in done:
            callback(self.fail_with, None)
        return len(done)

    def flush(self, timeout: float) -> int:
        self.flushes += 1
        self.poll(0)
        return 0

    def list_topics(self, topic: str | None = None, timeout: float = -1):
        self.calls.append("list_topics")
        if isinstance(self.metadata, Exception):
            raise self.metadata
        return self.metadata


def make(producer: FakeProducer | None = None) -> tuple[KafkaClickSink, FakeProducer, list[str]]:
    fake = producer or FakeProducer({})
    warnings: list[str] = []

    def factory(config: dict) -> FakeProducer:
        fake.config = config
        return fake

    return KafkaClickSink(SETTINGS, producer_factory=factory, warn=warnings.append), fake, warnings


def test_publishes_click_record_keyed_by_session() -> None:
    sink, fake, _ = make()
    sink.publish(VIEW)
    sink.publish(CART)
    sink.close()
    assert [(t, k) for t, k, _ in fake.produced] == [
        ("clickstream", b"s-1"),
        ("clickstream", b"s-1"),
    ]
    assert [json.loads(v) for _, _, v in fake.produced] == [click_record(VIEW), click_record(CART)]
    assert b" " not in fake.produced[0][2]  # 공백 없는 separators
    assert sink.stats.sent == 2 and sink.stats.failed == 0


def test_producer_gets_defaults() -> None:
    _, fake, _ = make()
    assert fake.config["acks"] == "all"
    assert fake.config["enable.idempotence"] is True
    assert fake.config["allow.auto.create.topics"] is False


def test_keeps_publish_order() -> None:
    sink, fake, _ = make()
    events = [
        ClickEvent(f"e-{i}", "view", "m-1", "a", datetime(2026, 10, 12, tzinfo=UTC), "s-1")
        for i in range(20)
    ]
    for event in events:
        sink.publish(event)
    assert [json.loads(v)["event_id"] for _, _, v in fake.produced] == [e.event_id for e in events]


def test_buffer_error_is_retried() -> None:
    fake = FakeProducer({})
    fake.buffer_errors = 2
    sink, fake, warnings = make(fake)
    sink.publish(VIEW)
    sink.close()
    assert len(fake.produced) == 1
    assert sink.stats.sent == 1 and sink.stats.failed == 0
    assert warnings == []


def test_buffer_error_that_persists_is_counted_not_raised() -> None:
    fake = FakeProducer({})
    fake.buffer_errors = 100
    sink, fake, warnings = make(fake)
    sink.publish(VIEW)
    sink.publish(CART)
    assert fake.produced == []
    assert sink.stats.failed == 2
    assert len(warnings) == 1


def test_produce_kafka_exception_is_counted() -> None:
    sink, fake, warnings = make()

    def boom(*args, **kwargs) -> None:
        raise KafkaException(KafkaError(KafkaError._UNKNOWN_TOPIC))

    fake.produce = boom  # type: ignore[method-assign]
    sink.publish(VIEW)
    assert sink.stats.failed == 1
    assert len(warnings) == 1


def test_delivery_failures_counted_and_warned_once() -> None:
    sink, fake, warnings = make()
    fake.fail_with = KafkaError(KafkaError._MSG_TIMED_OUT, "localhost:29092/bootstrap down")
    for _ in range(5):
        sink.publish(VIEW)
    sink.close()
    assert sink.stats.failed == 5 and sink.stats.sent == 0
    assert len(warnings) == 1
    assert "_MSG_TIMED_OUT" in warnings[0]
    for text in warnings:
        assert "29092" not in text and "kafka.internal" not in text
        assert "m-1" not in text and "0108775015" not in text and "s-1" not in text


def test_close_flushes_and_is_idempotent() -> None:
    sink, fake, _ = make()
    sink.publish(VIEW)
    sink.close()
    sink.close()
    assert fake.flushes == 1
    assert sink.stats.sent == 1


def test_unflushed_messages_count_as_failed() -> None:
    sink, fake, warnings = make()
    fake.flush = lambda timeout: 3  # type: ignore[method-assign]
    sink.close()
    assert sink.stats.failed == 3
    assert len(warnings) == 1


def test_publish_after_close_raises() -> None:
    sink, _, _ = make()
    sink.close()
    with pytest.raises(RuntimeError):
        sink.publish(VIEW)


def test_check_ready_passes_when_topic_exists() -> None:
    sink, fake, _ = make()
    sink.check_ready()
    assert fake.calls == ["list_topics"]  # produce도 토픽 생성도 하지 않는다


def test_check_ready_unreachable_broker() -> None:
    sink, fake, _ = make()
    fake.metadata = KafkaException(KafkaError(KafkaError._TRANSPORT, "b-1.kafka.internal:9093"))
    with pytest.raises(ClickSinkError) as info:
        sink.check_ready()
    assert "kafka.internal" not in str(info.value)
    assert "produce" not in fake.calls


@pytest.mark.parametrize(
    "topics",
    [
        {},
        {"clickstream": FakeTopic(error=KafkaError(KafkaError.UNKNOWN_TOPIC_OR_PART))},
        {"clickstream": FakeTopic(partitions={})},
    ],
)
def test_check_ready_missing_topic(topics: dict) -> None:
    sink, fake, _ = make()
    fake.metadata = FakeMetadata(topics)
    with pytest.raises(ClickSinkError):
        sink.check_ready()
    assert "produce" not in fake.calls
