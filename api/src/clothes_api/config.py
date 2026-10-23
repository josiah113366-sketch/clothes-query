"""환경 변수 설정. 접속 주소·비밀번호·인증서 경로는 출력하지 않는다."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

SECURITY_PROTOCOLS = ("PLAINTEXT", "SSL")


class ConfigError(RuntimeError):
    """설정이 잘못됐을 때. 메시지에 접속 정보를 담지 않는다."""


@dataclass(frozen=True)
class KafkaSettings:
    bootstrap: str = ""
    security_protocol: str = "PLAINTEXT"
    ssl_ca_file: str = ""
    ssl_cert_file: str = ""
    ssl_key_file: str = ""

    def __repr__(self) -> str:  # 주소와 경로가 출력에 섞이지 않게 한다
        return f"KafkaSettings(security_protocol={self.security_protocol!r})"


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    kafka: KafkaSettings = KafkaSettings()
    click_topic: str = "clickstream"
    pool_min: int = 1
    pool_max: int = 10
    pool_timeout_seconds: float = 2.0
    log_level: str = "INFO"

    def __repr__(self) -> str:
        return (
            f"Settings(click_topic={self.click_topic!r}, pool_max={self.pool_max}, "
            f"kafka={self.kafka!r})"
        )


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name}은 정수여야 합니다.") from None


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name}은 숫자여야 합니다.") from None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """DATABASE_URL이 없으면 PG* 표준 환경 변수(PGHOST 등)로 libpq가 접속한다."""
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
    bootstrap = env.get("KAFKA_BOOTSTRAP", "").strip()
    if not bootstrap:
        raise ConfigError("KAFKA_BOOTSTRAP이 설정되지 않았습니다.")
    pool_min = _int(env, "API_DB_POOL_MIN", 1)
    pool_max = _int(env, "API_DB_POOL_MAX", 10)
    if not 1 <= pool_min <= pool_max:
        raise ConfigError("API_DB_POOL_MIN은 1 이상, API_DB_POOL_MAX 이하여야 합니다.")
    return Settings(
        database_url=env.get("DATABASE_URL", "").strip(),
        kafka=KafkaSettings(
            bootstrap=bootstrap,
            security_protocol=protocol,
            ssl_ca_file=env.get("KAFKA_SSL_CA_FILE", "").strip(),
            ssl_cert_file=cert,
            ssl_key_file=key,
        ),
        click_topic=env.get("CLICK_TOPIC", "").strip() or "clickstream",
        pool_min=pool_min,
        pool_max=pool_max,
        pool_timeout_seconds=_float(env, "API_DB_POOL_TIMEOUT", 2.0),
        log_level=env.get("LOG_LEVEL", "").strip().upper() or "INFO",
    )
