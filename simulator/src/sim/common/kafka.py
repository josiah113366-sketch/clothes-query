"""Kafka 공용 설정. behavior(발행)와 clickstream(토픽 관리·확인)이 서로 import하지 않고 같은 값을 쓴다.

접속 주소와 인증서 경로는 환경 변수로 받는다. 출력·repr·예외 메시지에 싣지 않는다.
TLS(KAFKA_SECURITY_PROTOCOL=SSL)는 설정 연결까지만 했고 로컬에서는 검증하지 못했다.
"""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from sim.common.config import DEFAULT_KAFKA_BOOTSTRAP, ConfigError

CLICK_TOPIC = "clickstream"
CLICK_TOPIC_PARTITIONS = 3
TOPIC_RETENTION_MS = 259_200_000  # 72시간 (인프라 토픽 계약과 같다)
LOCAL_REPLICATION = 1

SECURITY_PROTOCOLS = ("PLAINTEXT", "SSL")
LOCAL_HOSTS = ("localhost", "127.0.0.1")

PRODUCER_DEFAULTS: dict[str, object] = {
    "acks": "all",
    "enable.idempotence": True,
    "linger.ms": 50,
    "message.timeout.ms": 10_000,
    "allow.auto.create.topics": False,  # 토픽이 없을 때 1파티션으로 자동 생성되는 것을 막는다
}


@dataclass(frozen=True)
class KafkaSettings:
    bootstrap: str = DEFAULT_KAFKA_BOOTSTRAP
    security_protocol: str = "PLAINTEXT"
    ssl_ca_file: str = ""
    ssl_cert_file: str = ""
    ssl_key_file: str = ""

    def __repr__(self) -> str:  # 주소와 경로가 출력에 섞이지 않게 한다
        return f"KafkaSettings(security_protocol={self.security_protocol!r})"

    @property
    def is_local(self) -> bool:
        return is_local_bootstrap(self.bootstrap)


def load_kafka_settings(env: Mapping[str, str] | None = None) -> KafkaSettings:
    """환경 변수에서 읽는다. simulator/.env는 load_config가 이미 읽어 둔 상태에서 부른다."""
    env = os.environ if env is None else env
    protocol = env.get("KAFKA_SECURITY_PROTOCOL", "").strip().upper() or "PLAINTEXT"
    if protocol not in SECURITY_PROTOCOLS:
        raise ConfigError(
            f"KAFKA_SECURITY_PROTOCOL은 {', '.join(SECURITY_PROTOCOLS)} 중 하나여야 합니다."
        )
    cert = env.get("KAFKA_SSL_CERT_FILE", "").strip()
    key = env.get("KAFKA_SSL_KEY_FILE", "").strip()
    if bool(cert) != bool(key):
        raise ConfigError("KAFKA_SSL_CERT_FILE과 KAFKA_SSL_KEY_FILE은 함께 설정해야 합니다.")
    return KafkaSettings(
        bootstrap=env.get("KAFKA_BOOTSTRAP", "").strip() or DEFAULT_KAFKA_BOOTSTRAP,
        security_protocol=protocol,
        ssl_ca_file=env.get("KAFKA_SSL_CA_FILE", "").strip(),
        ssl_cert_file=cert,
        ssl_key_file=key,
    )


def _base_config(settings: KafkaSettings) -> dict[str, object]:
    config: dict[str, object] = {
        "bootstrap.servers": settings.bootstrap,
        "security.protocol": settings.security_protocol,
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


def producer_config(settings: KafkaSettings) -> dict[str, object]:
    return {**_base_config(settings), **PRODUCER_DEFAULTS}


def admin_config(settings: KafkaSettings) -> dict[str, object]:
    # 토픽 메타데이터 조회가 토픽을 만들어 버리지 않게 한다
    return {**_base_config(settings), "allow.auto.create.topics": False}


def consumer_config(settings: KafkaSettings, group_id: str) -> dict[str, object]:
    return {
        **_base_config(settings),
        "group.id": group_id,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "enable.partition.eof": False,
        "allow.auto.create.topics": False,
    }


def quiet_logger() -> logging.Logger:
    """librdkafka 내부 로그를 버리는 로거. 그 로그에는 브로커 주소가 들어 있다."""
    logger = logging.getLogger("sim.kafka.librdkafka")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def is_local_bootstrap(bootstrap: str) -> bool:
    """모든 주소의 호스트가 localhost 또는 127.0.0.1이면 참."""
    entries = [entry.strip() for entry in bootstrap.split(",") if entry.strip()]
    if not entries:
        return False
    for entry in entries:
        host = entry.rsplit(":", 1)[0] if ":" in entry else entry
        if host not in LOCAL_HOSTS:
            return False
    return True
