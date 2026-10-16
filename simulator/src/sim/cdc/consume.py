"""Kafka에서 읽기 (confluent-kafka). 읽어도 아무 흔적이 남지 않는다: 임시 소비자 그룹, offset 커밋 없음.

메시지를 쌓아 두지 않고 하나씩 넘겨 준다. 원문을 파일로 저장하지 않는다.
"""

import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient

from sim.cdc import params

_METADATA_TIMEOUT = 10


class ConsumeError(RuntimeError):
    """읽기 실패. 메시지에 메시지 내용을 담지 않는다."""


@dataclass(frozen=True)
class RawMessage:
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None


def _consumer(bootstrap: str) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"sim-cdc-verify-{uuid.uuid4().hex}",  # 매번 새 임시 그룹
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "enable.partition.eof": False,
        }
    )


def topic_exists(bootstrap: str, topic: str) -> bool:
    admin = AdminClient({"bootstrap.servers": bootstrap})
    try:
        metadata = admin.list_topics(topic=topic, timeout=_METADATA_TIMEOUT)
    except KafkaException:
        raise ConsumeError("Kafka에 닿지 않습니다.") from None
    entry = metadata.topics.get(topic)
    return entry is not None and entry.error is None


def partition_offsets(bootstrap: str, topic: str) -> dict[int, tuple[int, int]]:
    """파티션별 (시작 offset, 끝 offset). 토픽이 없으면 빈 dict."""
    if not topic_exists(bootstrap, topic):
        return {}
    consumer = _consumer(bootstrap)
    try:
        metadata = consumer.list_topics(topic=topic, timeout=_METADATA_TIMEOUT)
        result: dict[int, tuple[int, int]] = {}
        for partition in metadata.topics[topic].partitions:
            low, high = consumer.get_watermark_offsets(
                TopicPartition(topic, partition), timeout=_METADATA_TIMEOUT
            )
            result[partition] = (low, high)
        return result
    except KafkaException:
        raise ConsumeError("토픽 offset을 읽지 못했습니다.") from None
    finally:
        consumer.close()


def total_messages(offsets: dict[int, tuple[int, int]]) -> int:
    return sum(high - low for low, high in offsets.values())


def iter_messages(
    bootstrap: str,
    topic: str,
    idle_seconds: float = params.CONSUME_IDLE_SECONDS,
) -> Iterator[RawMessage]:
    """토픽을 처음부터 읽는다. 시작할 때 끝 offset을 한 번 기록하고 거기까지 읽으면 멈춘다.

    idle_seconds 동안 새 메시지가 없는데 끝 offset에 못 닿으면 ConsumeError.
    """
    offsets = partition_offsets(bootstrap, topic)
    if not offsets:
        raise ConsumeError(f"토픽 {topic}이 없습니다.")
    ends = {p: high for p, (low, high) in offsets.items() if high > low}
    if not ends:
        return
    consumer = _consumer(bootstrap)
    try:
        consumer.assign([TopicPartition(topic, p, offsets[p][0]) for p in offsets])
        last_progress = time.monotonic()
        while ends:
            message = consumer.poll(1.0)
            if message is None:
                if time.monotonic() - last_progress > idle_seconds:
                    raise ConsumeError(
                        f"{idle_seconds:.0f}초 동안 새 메시지가 없는데 끝 offset에 닿지 못했습니다."
                    )
                continue
            error = message.error()
            if error is not None:
                if error.code() == KafkaError._PARTITION_EOF:
                    continue
                raise ConsumeError(f"읽는 중 Kafka 오류 (code={error.code()})")
            last_progress = time.monotonic()
            partition, offset = message.partition(), message.offset()
            if partition in ends:
                yield RawMessage(partition, offset, message.key(), message.value())
                if offset + 1 >= ends[partition]:
                    del ends[partition]
    finally:
        consumer.close()


def delete_topics(bootstrap: str, topics: list[str]) -> list[str]:
    """있는 토픽만 지우고, 지운 토픽 이름을 돌려준다."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    existing = [t for t in topics if topic_exists(bootstrap, t)]
    if not existing:
        return []
    for topic, future in admin.delete_topics(existing, operation_timeout=30).items():
        try:
            future.result()
        except KafkaException:
            raise ConsumeError(f"토픽 {topic}을 지우지 못했습니다.") from None
    return existing
