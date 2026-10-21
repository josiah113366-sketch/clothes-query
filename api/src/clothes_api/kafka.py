"""clickstream 발행. 실패하면 버리고 센다(주문 흐름을 막지 않는다).

브로커 주소·인증서 경로는 출력하지 않는다. librdkafka 내부 로그(주소 포함)는 버린다.
"""

import json
import logging
from collections.abc import Callable, Sequence
from typing import Protocol

from confluent_kafka import KafkaError, KafkaException, Message, Producer

from clothes_api.config import KafkaSettings
from clothes_api.metrics import Metrics
from clothes_api.schemas import ClickEvent

PRODUCER_DEFAULTS: dict[str, object] = {
    "acks": "all",
    "enable.idempotence": True,
    "linger.ms": 50,
    "message.timeout.ms": 10_000,
    "allow.auto.create.topics": False,
}


class ClickPublisher(Protocol):
    def publish(self, events: Sequence[ClickEvent]) -> tuple[int, int]:
        """(받음, 실패) 수. 예외를 던지지 않는다."""
        ...

    def ready(self) -> bool: ...

    def close(self) -> None: ...


def producer_config(settings: KafkaSettings) -> dict[str, object]:
    config: dict[str, object] = {
        "bootstrap.servers": settings.bootstrap,
        "security.protocol": settings.security_protocol,
        **PRODUCER_DEFAULTS,
    }
    if settings.security_protocol == "SSL":
        for key, value in (
            ("ssl.ca.location", settings.ssl_ca_file),
            ("ssl.certificate.location", settings.ssl_cert_file),
            ("ssl.key.location", settings.ssl_key_file),
        ):
            if value:
                config[key] = value
    return config


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("clothes_api.librdkafka")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class KafkaClickPublisher:
    def __init__(
        self,
        settings: KafkaSettings,
        topic: str,
        metrics: Metrics,
        producer_factory: Callable[[dict], Producer] | None = None,
    ) -> None:
        factory = producer_factory or (lambda c: Producer(c, logger=quiet_logger()))
        self._producer = factory(producer_config(settings))
        self._topic = topic
        self._metrics = metrics

    def _delivered(self, error: KafkaError | None, message: Message) -> None:
        self._metrics.kafka_produced.labels("failed" if error else "ok").inc()

    def publish(self, events: Sequence[ClickEvent]) -> tuple[int, int]:
        accepted = failed = 0
        for event in events:
            value = json.dumps(event.record(), separators=(",", ":"), ensure_ascii=False)
            try:
                self._producer.produce(
                    self._topic,
                    value=value.encode(),
                    key=event.session_id.encode(),
                    on_delivery=self._delivered,
                )
                accepted += 1
            except (BufferError, KafkaException):
                failed += 1
                self._metrics.kafka_produced.labels("rejected").inc()
            self._producer.poll(0)
        return accepted, failed

    def ready(self) -> bool:
        try:
            metadata = self._producer.list_topics(self._topic, timeout=2)
        except KafkaException:
            return False
        topic = metadata.topics.get(self._topic)
        return topic is not None and topic.error is None

    def close(self) -> None:
        self._producer.flush(10)
