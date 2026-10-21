"""clickstream 토픽 다루기 (confluent-kafka). 브로커 주소와 메시지 내용은 예외 메시지에 싣지 않는다.

읽기는 흔적을 남기지 않는다: 매번 새 임시 컨슈머 그룹, offset 저장 없음.
"""

import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient, ConfigResource, NewTopic

from sim.common.kafka import (
    LOCAL_REPLICATION,
    TOPIC_RETENTION_MS,
    KafkaSettings,
    admin_config,
    consumer_config,
    quiet_logger,
)

METADATA_TIMEOUT_SECONDS = 10.0
OPERATION_TIMEOUT_SECONDS = 30.0
IDLE_SECONDS = 15.0


class TopicError(RuntimeError):
    """Kafka 작업 실패. 메시지에 브로커 주소, 메시지 내용을 싣지 않는다."""


@dataclass(frozen=True)
class TopicInfo:
    partitions: int
    retention_ms: str | None


@dataclass(frozen=True)
class ClickMessage:
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None


def _admin(settings: KafkaSettings) -> AdminClient:
    return AdminClient(admin_config(settings), logger=quiet_logger())


def _consumer(settings: KafkaSettings) -> Consumer:
    group = f"sim-clickstream-verify-{uuid.uuid4().hex}"  # 매번 새 임시 그룹
    return Consumer(consumer_config(settings, group), logger=quiet_logger())


def describe(settings: KafkaSettings, topic: str) -> TopicInfo | None:
    """토픽이 없으면 None. 이 조회는 토픽을 만들지 않는다(자동 생성 꺼 둠)."""
    admin = _admin(settings)
    try:
        metadata = admin.list_topics(topic=topic, timeout=METADATA_TIMEOUT_SECONDS)
    except KafkaException:
        raise TopicError("Kafka에 닿지 않습니다.") from None
    entry = metadata.topics.get(topic)
    if entry is None or entry.error is not None or not entry.partitions:
        return None
    retention: str | None = None
    try:
        resource = ConfigResource(ConfigResource.Type.TOPIC, topic)
        configs = admin.describe_configs([resource])[resource].result(
            timeout=METADATA_TIMEOUT_SECONDS
        )
        if "retention.ms" in configs:
            retention = configs["retention.ms"].value
    except KafkaException:
        retention = None
    return TopicInfo(partitions=len(entry.partitions), retention_ms=retention)


def create(settings: KafkaSettings, topic: str, partitions: int) -> None:
    new = NewTopic(
        topic,
        num_partitions=partitions,
        replication_factor=LOCAL_REPLICATION,
        config={"retention.ms": str(TOPIC_RETENTION_MS)},
    )
    admin = _admin(settings)  # 결과를 받을 때까지 클라이언트를 붙잡아 둔다
    futures = admin.create_topics([new], operation_timeout=OPERATION_TIMEOUT_SECONDS)
    try:
        futures[topic].result()
    except KafkaException:
        raise TopicError(f"토픽 {topic}을(를) 만들지 못했습니다.") from None


def delete(settings: KafkaSettings, topic: str) -> None:
    admin = _admin(settings)
    futures = admin.delete_topics([topic], operation_timeout=OPERATION_TIMEOUT_SECONDS)
    try:
        futures[topic].result()
    except KafkaException:
        raise TopicError(f"토픽 {topic}을(를) 지우지 못했습니다.") from None


def offsets(settings: KafkaSettings, topic: str, partitions: int) -> dict[int, tuple[int, int]]:
    """파티션별 (low, high) offset."""
    consumer = _consumer(settings)
    try:
        result: dict[int, tuple[int, int]] = {}
        for partition in range(partitions):
            low, high = consumer.get_watermark_offsets(
                TopicPartition(topic, partition), timeout=METADATA_TIMEOUT_SECONDS
            )
            result[partition] = (low, high)
        return result
    except KafkaException:
        raise TopicError("토픽 offset을 읽지 못했습니다.") from None
    finally:
        consumer.close()


def read_all(
    settings: KafkaSettings,
    topic: str,
    partition_offsets: dict[int, tuple[int, int]],
    idle_seconds: float = IDLE_SECONDS,
) -> Iterator[ClickMessage]:
    """처음(low)부터 시작 시점의 끝(high)까지 한 번 읽는다. 그 뒤에 들어온 메시지는 읽지 않는다."""
    ends = {p: high for p, (low, high) in partition_offsets.items() if high > low}
    if not ends:
        return
    consumer = _consumer(settings)
    try:
        consumer.assign([TopicPartition(topic, p, partition_offsets[p][0]) for p in ends])
        last_progress = time.monotonic()
        while ends:
            message = consumer.poll(1.0)
            if message is None:
                if time.monotonic() - last_progress > idle_seconds:
                    raise TopicError(
                        f"{idle_seconds:.0f}초 동안 새 메시지가 없는데 끝 offset에 닿지 못했습니다."
                    )
                continue
            error = message.error()
            if error is not None:
                if error.code() == KafkaError._PARTITION_EOF:
                    continue
                raise TopicError(f"읽는 중 Kafka 오류 ({error.name()})")
            last_progress = time.monotonic()
            partition, offset = message.partition(), message.offset()
            if partition not in ends or offset >= ends[partition]:
                continue
            yield ClickMessage(partition, offset, message.key(), message.value())
            if offset + 1 >= ends[partition]:
                del ends[partition]
    except KafkaException:
        raise TopicError("토픽을 읽지 못했습니다.") from None
    finally:
        consumer.close()
