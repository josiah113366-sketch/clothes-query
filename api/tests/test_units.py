import json
from types import SimpleNamespace

import pytest

from clothes_api.config import ConfigError, load_settings
from clothes_api.kafka import KafkaClickPublisher, producer_config
from clothes_api.metrics import Metrics
from clothes_api.schemas import ClickEvent, NewMember
from clothes_api.store import TRANSITIONS

BASE_ENV = {"KAFKA_BOOTSTRAP": "kafka.example.internal:9093"}


def test_settings_defaults_and_repr_hides_endpoints():
    settings = load_settings({**BASE_ENV, "DATABASE_URL": "postgresql://u:secret@db.example/x"})
    assert settings.click_topic == "clickstream" and settings.pool_max == 10
    text = repr(settings)
    assert "secret" not in text and "example" not in text


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**BASE_ENV, "KAFKA_SECURITY_PROTOCOL": "SASL"},
        {**BASE_ENV, "KAFKA_SSL_CERT_FILE": "/c"},
        {**BASE_ENV, "API_DB_POOL_MAX": "0"},
        {**BASE_ENV, "API_DB_POOL_TIMEOUT": "x"},
    ],
)
def test_settings_errors(env):
    with pytest.raises(ConfigError):
        load_settings(env)


def test_producer_config_tls():
    settings = load_settings(
        {
            **BASE_ENV,
            "KAFKA_SECURITY_PROTOCOL": "SSL",
            "KAFKA_SSL_CA_FILE": "/ca",
            "KAFKA_SSL_CERT_FILE": "/c",
            "KAFKA_SSL_KEY_FILE": "/k",
        }
    )
    config = producer_config(settings.kafka)
    assert config["security.protocol"] == "SSL"
    assert config["ssl.certificate.location"] == "/c" and config["acks"] == "all"
    assert config["enable.idempotence"] is True and config["allow.auto.create.topics"] is False


class FakeProducer:
    def __init__(self, config: dict, fail: bool = False) -> None:
        self.config = config
        self.sent: list[tuple] = []
        self.fail = fail

    def produce(self, topic, value, key, on_delivery):
        if self.fail:
            raise BufferError("full")
        self.sent.append((topic, key, value))
        on_delivery(None, None)

    def poll(self, timeout):
        return 0

    def flush(self, timeout):
        return 0

    def list_topics(self, topic, timeout):
        return SimpleNamespace(topics={topic: SimpleNamespace(error=None)})


def _event(**over) -> ClickEvent:
    data = {
        "event_id": "e-1",
        "event_type": "view",
        "member_id": "m-1",
        "article_id": "0108775015",
        "event_time": "2026-10-20T15:20:05.123456+09:00",
        "session_id": "s-1",
    }
    data.update(over)
    return ClickEvent(**data)


def test_publisher_key_value_and_metrics():
    metrics = Metrics()
    producer = FakeProducer({})
    publisher = KafkaClickPublisher(
        load_settings(BASE_ENV).kafka, "clickstream", metrics, lambda c: producer
    )
    assert publisher.publish([_event()]) == (1, 0)
    topic, key, value = producer.sent[0]
    assert topic == "clickstream" and key == b"s-1"
    record = json.loads(value)
    assert record["event_time"] == "2026-10-20T06:20:05.123456Z"
    assert publisher.ready() is True
    assert metrics.kafka_produced.labels("ok")._value.get() == 1


def test_publisher_counts_buffer_errors():
    metrics = Metrics()
    publisher = KafkaClickPublisher(
        load_settings(BASE_ENV).kafka,
        "clickstream",
        metrics,
        lambda c: FakeProducer(c, fail=True),
    )
    assert publisher.publish([_event(), _event(event_id="e-2")]) == (0, 2)
    assert metrics.kafka_produced.labels("rejected")._value.get() == 2


def test_member_repr_has_no_pii():
    member = NewMember(
        member_id="11111111-1111-4111-8111-111111111111",
        name="홍길동",
        email="pii@example.com",
        phone="010-0000-0000",
        birth_date="1990-01-01",
        password_hash="h",
        gender="F",
        age_band="30s",
        region_sigungu="서울특별시 중구",
        signup_channel="web",
        marketing_consent=False,
        signup_at="2026-10-20T00:00:00Z",
    )
    assert "pii" not in repr(member) and "홍길동" not in str(member)


def test_transitions_match_simulator():
    # 시뮬레이터 behavior/payment.py next_transition, runner.py와 같아야 한다
    assert TRANSITIONS == {
        "PLACED": {"PAID", "PAYMENT_FAILED", "CANCELLED"},
        "PAID": {"SHIPPED", "CANCELLED"},
        "SHIPPED": {"DELIVERED"},
        "DELIVERED": {"REFUNDED"},
    }
