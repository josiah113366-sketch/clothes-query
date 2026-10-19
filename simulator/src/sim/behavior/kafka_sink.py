"""클릭 Sink의 Kafka 구현. 클릭 로그만 Kafka 토픽 clickstream에 직접 발행한다.

- 키는 session_id라서 같은 방문의 view → cart_add 순서가 한 파티션 안에서 지켜진다.
- 값은 click_record(event)의 6개 필드를 그대로 JSON으로 낸다 (JsonlClickSink와 같은 내용).
- 전송 실패는 버리고 센다. 클릭이 주문 흐름(DB)을 멈추게 하면 안 된다.
- 브로커 주소와 이벤트 내용은 출력하지 않는다.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from confluent_kafka import KafkaError, KafkaException, Producer

from sim.behavior.model import ClickEvent
from sim.behavior.sink import click_record
from sim.common.kafka import CLICK_TOPIC, KafkaSettings, producer_config, quiet_logger

READY_TIMEOUT_SECONDS = 10.0
CLOSE_FLUSH_SECONDS = 30.0
BUFFER_RETRIES = 3
BUFFER_WAIT_SECONDS = 0.5


class ClickSinkError(RuntimeError):
    """시작할 수 없는 상태. 메시지에 브로커 주소를 싣지 않는다."""


class ProducerLike(Protocol):
    def produce(self, topic: str, value: bytes, key: bytes, on_delivery: Callable) -> None: ...

    def poll(self, timeout: float) -> int: ...

    def flush(self, timeout: float) -> int: ...

    def list_topics(self, topic: str | None = None, timeout: float = -1) -> object: ...


@dataclass(frozen=True)
class ClickStats:
    sent: int
    failed: int


def _stderr_warn(message: str) -> None:
    print(f"경고: {message}", file=sys.stderr, flush=True)


class KafkaClickSink:
    def __init__(
        self,
        settings: KafkaSettings,
        topic: str = CLICK_TOPIC,
        producer_factory: Callable[[dict], ProducerLike] | None = None,
        warn: Callable[[str], None] = _stderr_warn,
    ) -> None:
        self.topic = topic
        factory = producer_factory or (lambda config: Producer(config, logger=quiet_logger()))
        self._producer: ProducerLike | None = factory(producer_config(settings))
        self._warn = warn
        self._sent = 0
        self._failed = 0
        self._warned = False

    def check_ready(self) -> None:
        """브로커에 닿는지, 토픽이 있는지 확인한다. 토픽을 만들지 않는다(자동 생성 꺼 둠)."""
        producer = self._require()
        try:
            metadata = producer.list_topics(topic=self.topic, timeout=READY_TIMEOUT_SECONDS)
        except KafkaException:
            raise ClickSinkError("Kafka 브로커에 닿지 않습니다.") from None
        entry = metadata.topics.get(self.topic)  # type: ignore[attr-defined]
        if entry is None or entry.error is not None or not entry.partitions:
            raise ClickSinkError(f"토픽 {self.topic}이(가) 없습니다.")

    def publish(self, event: ClickEvent) -> None:
        producer = self._require()
        value = json.dumps(click_record(event), ensure_ascii=False, separators=(",", ":"))
        key = event.session_id.encode("utf-8")
        for attempt in range(BUFFER_RETRIES + 1):
            try:
                producer.produce(
                    self.topic, value=value.encode("utf-8"), key=key, on_delivery=self._on_delivery
                )
                break
            except BufferError:
                if attempt == BUFFER_RETRIES:
                    self._count_failure("프로듀서 내부 큐가 가득 찼습니다")
                    return
                producer.poll(BUFFER_WAIT_SECONDS)
            except KafkaException as error:
                self._count_failure(_error_name(error.args[0] if error.args else None))
                return
        producer.poll(0)

    def close(self) -> None:
        """남은 메시지를 보내고(최대 30초) 닫는다. 끝내 못 보낸 건은 실패로 센다."""
        if self._producer is None:
            return
        producer, self._producer = self._producer, None
        remaining = producer.flush(CLOSE_FLUSH_SECONDS)
        if remaining > 0:
            self._failed += remaining
            self._warn_once("종료할 때 보내지 못한 클릭이 있습니다")

    @property
    def stats(self) -> ClickStats:
        return ClickStats(sent=self._sent, failed=self._failed)

    def _require(self) -> ProducerLike:
        if self._producer is None:
            raise RuntimeError("닫힌 클릭 Sink입니다.")
        return self._producer

    def _on_delivery(self, error: KafkaError | None, message: object) -> None:
        if error is None:
            self._sent += 1
        else:
            self._count_failure(_error_name(error))

    def _count_failure(self, reason: str) -> None:
        self._failed += 1
        self._warn_once(f"클릭 발행에 실패했습니다 ({reason}). 이후 실패는 건수만 셉니다")

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            self._warn(message)


def _error_name(error: object) -> str:
    """KafkaError의 코드 이름만 쓴다 (설명 문자열에는 브로커 주소가 들어갈 수 있다)."""
    name = getattr(error, "name", None)
    return name() if callable(name) else "알 수 없는 오류"
