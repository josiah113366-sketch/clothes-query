import pytest

from sim.common.config import ConfigError
from sim.common.kafka import (
    KafkaSettings,
    admin_config,
    consumer_config,
    is_local_bootstrap,
    load_kafka_settings,
    producer_config,
)


def test_defaults_are_local_plaintext() -> None:
    settings = load_kafka_settings({})
    assert settings.bootstrap == "localhost:29092"
    assert settings.security_protocol == "PLAINTEXT"
    assert settings.is_local


def test_reads_tls_env() -> None:
    settings = load_kafka_settings(
        {
            "KAFKA_BOOTSTRAP": "b-1.kafka.internal:9093",
            "KAFKA_SECURITY_PROTOCOL": "ssl",
            "KAFKA_SSL_CA_FILE": "/certs/ca.pem",
            "KAFKA_SSL_CERT_FILE": "/certs/client.pem",
            "KAFKA_SSL_KEY_FILE": "/certs/client.key",
        }
    )
    assert settings.security_protocol == "SSL"
    config = producer_config(settings)
    assert config["ssl.ca.location"] == "/certs/ca.pem"
    assert config["ssl.certificate.location"] == "/certs/client.pem"
    assert config["ssl.key.location"] == "/certs/client.key"
    assert not settings.is_local


def test_rejects_unknown_protocol() -> None:
    with pytest.raises(ConfigError):
        load_kafka_settings({"KAFKA_SECURITY_PROTOCOL": "SASL_SSL"})


def test_cert_and_key_go_together() -> None:
    with pytest.raises(ConfigError):
        load_kafka_settings({"KAFKA_SECURITY_PROTOCOL": "SSL", "KAFKA_SSL_CERT_FILE": "/c.pem"})


def test_producer_defaults() -> None:
    config = producer_config(KafkaSettings())
    assert config["acks"] == "all"
    assert config["enable.idempotence"] is True
    assert config["linger.ms"] == 50
    assert config["message.timeout.ms"] == 10_000
    assert config["allow.auto.create.topics"] is False
    assert config["security.protocol"] == "PLAINTEXT"
    assert not any(key.startswith("ssl.") for key in config)


def test_admin_and_consumer_never_auto_create() -> None:
    settings = KafkaSettings()
    assert admin_config(settings)["allow.auto.create.topics"] is False
    consumer = consumer_config(settings, "g1")
    assert consumer["allow.auto.create.topics"] is False
    assert consumer["group.id"] == "g1"
    assert consumer["enable.auto.commit"] is False


def test_repr_hides_address_and_paths() -> None:
    settings = KafkaSettings(
        bootstrap="b-1.kafka.internal:9093",
        security_protocol="SSL",
        ssl_ca_file="/certs/ca.pem",
        ssl_cert_file="/certs/c.pem",
        ssl_key_file="/certs/c.key",
    )
    text = repr(settings)
    assert "kafka.internal" not in text
    assert "/certs" not in text


@pytest.mark.parametrize(
    ("bootstrap", "expected"),
    [
        ("localhost:29092", True),
        ("127.0.0.1:9092", True),
        ("localhost:29092,127.0.0.1:9092", True),
        ("localhost", True),
        ("kafka.example.internal:9093", False),
        ("localhost:29092,kafka:9092", False),
        ("10.0.0.5:9092", False),
        ("", False),
    ],
)
def test_is_local_bootstrap(bootstrap: str, expected: bool) -> None:
    assert is_local_bootstrap(bootstrap) is expected
