"""Gold B 적재 잡: Kafka 토픽을 Spark Structured Streaming으로 1분마다 읽어 원장 ①②④에 쌓는다 (4단계).

설계는 docs/design/gold-b/README.md 「역할 경계와 전체 흐름」, 「처리 규칙」, 4단계.
설정은 config/gold_b.yaml과 환경변수이고, 기본값과 부르는 방법은 같은 폴더의 README.md에 있다.

1분 묶음 하나(write_batch)에 하는 일
  1. 메시지마다 형식 검사를 하고 원장 줄을 만든다 (재처리 잡과 같은 ledger.message_rows).
     ② topic_messages에는 모든 메시지, ① payment_events에는 형식을 통과한 결제, ④ malformed_events에는 오류마다 한 줄.
  2. 줄을 이벤트 시각의 시간 폴더로 나눠 (표, 시간 폴더)마다 파일 하나로 쓴다. loaded_at은 그 묶음을 쓴 시각이다.
  3. 파일 이름은 그 파일에 든 메시지 위치로 정한다. Spark가 끝내지 못한 묶음을 다시 처리하면 같은 이름이라 덮어쓴다 (두 번 쌓이지 않음).

Kafka에서 어디까지 읽었는지는 Spark 체크포인트가 기억한다. Kafka에 처리 위치를 커밋하지 않는다.
build_query(Spark 연결)는 Docker의 Spark 4.1.3과 로컬 Kafka로 확인했다 (이 PC에서는 Spark가 바로 뜨지 않음). write_batch는 단위 시험으로 확인한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Mapping, Sequence

from pipelines.gold_b.ledger import (EVENT_TIME, Checker, KafkaMessage, Store, hour_folder, hour_of,
                                     message_rows, utc_naive)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "gold_b.yaml"
INGESTED_TABLES = ("topic_messages", "payment_events", "malformed_events")   # ③은 수집기가 쌓는다
SECURITY_PROTOCOLS = ("PLAINTEXT", "SSL")
STARTING_OFFSETS = ("earliest", "latest")


class ConfigError(ValueError):
    """설정이 잘못됐다."""


@dataclass(frozen=True)
class Config:
    """config/gold_b.yaml"""

    topics: tuple[str, ...]
    trigger_seconds: int = 60
    starting_offsets: str = "earliest"
    max_offsets_per_trigger: int = 20000


def load_config(path: str | Path = CONFIG_PATH) -> Config:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    topics = tuple(str(topic) for topic in data.get("topics") or ())
    config = Config(topics=topics,
                    trigger_seconds=int(data.get("trigger_seconds", 60)),
                    starting_offsets=str(data.get("starting_offsets", "earliest")),
                    max_offsets_per_trigger=int(data.get("max_offsets_per_trigger", 20000)))
    if not config.topics:
        raise ConfigError("topics가 비어 있다")
    if config.trigger_seconds < 1 or config.max_offsets_per_trigger < 1:
        raise ConfigError("trigger_seconds와 max_offsets_per_trigger는 1 이상이어야 한다")
    if config.starting_offsets not in STARTING_OFFSETS:
        raise ConfigError(f"starting_offsets는 {', '.join(STARTING_OFFSETS)} 중 하나여야 한다")
    return config


@dataclass(frozen=True)
class Settings:
    """환경변수로 받는 값. 주소·경로는 repr에 나오지 않게 한다 (로그에 남지 않게)."""

    ledger_root: str = field(repr=False)        # GOLD_B_LEDGER_ROOT: s3://<버킷>/gold_b 또는 로컬 폴더
    checkpoint: str = field(repr=False)         # GOLD_B_CHECKPOINT: Spark 체크포인트 (S3면 s3a://)
    bootstrap: str = field(repr=False)          # KAFKA_BOOTSTRAP
    security_protocol: str = "PLAINTEXT"        # KAFKA_SECURITY_PROTOCOL
    ssl_ca_file: str = field(default="", repr=False)
    ssl_cert_file: str = field(default="", repr=False)
    ssl_key_file: str = field(default="", repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        def get(key: str) -> str:
            return (env.get(key) or "").strip()

        missing = [key for key in ("GOLD_B_LEDGER_ROOT", "GOLD_B_CHECKPOINT", "KAFKA_BOOTSTRAP") if not get(key)]
        if missing:
            raise ConfigError(f"환경변수가 필요하다: {', '.join(missing)}")
        protocol = (get("KAFKA_SECURITY_PROTOCOL") or "PLAINTEXT").upper()
        if protocol not in SECURITY_PROTOCOLS:
            raise ConfigError(f"KAFKA_SECURITY_PROTOCOL은 {', '.join(SECURITY_PROTOCOLS)} 중 하나여야 한다")
        cert, key = get("KAFKA_SSL_CERT_FILE"), get("KAFKA_SSL_KEY_FILE")
        if bool(cert) != bool(key):
            raise ConfigError("KAFKA_SSL_CERT_FILE과 KAFKA_SSL_KEY_FILE은 함께 설정해야 한다")
        return cls(ledger_root=get("GOLD_B_LEDGER_ROOT"), checkpoint=get("GOLD_B_CHECKPOINT"),
                   bootstrap=get("KAFKA_BOOTSTRAP"), security_protocol=protocol,
                   ssl_ca_file=get("KAFKA_SSL_CA_FILE"), ssl_cert_file=cert, ssl_key_file=key)


# ---------- 묶음 하나 → 원장 파일 (Spark 없이 시험한다) ----------

def write_batch(messages: Sequence[KafkaMessage], *, checker: Checker, store: Store,
                loaded_at: datetime) -> dict:
    """묶음 하나의 메시지를 원장 ①②④의 시간 폴더 파일로 쓴다. 쓴 파일 수와 표별 줄 수를 돌려준다."""
    rows: dict[tuple[str, datetime], list[dict]] = {}
    positions: dict[tuple[str, datetime], set[tuple[str, int, int]]] = {}
    for message in messages:
        made = message_rows(message, checker(message), checker.rule_version, loaded_at)
        for table in INGESTED_TABLES:
            for row in made[table]:
                key = (table, hour_of(row[EVENT_TIME[table]]))
                rows.setdefault(key, []).append(row)
                positions.setdefault(key, set()).add(message.position)
    for (table, hour), items in rows.items():
        # 같은 메시지 묶음이면 같은 이름 → Spark가 묶음을 다시 처리해도 덮어써서 두 번 쌓이지 않는다
        digest = hashlib.sha256(json.dumps(sorted(positions[(table, hour)])).encode("utf-8")).hexdigest()[:16]
        store.write(f"{hour_folder(table, hour)}/part-ingest-{digest}.parquet", table, items)
    counts = {table: sum(len(items) for (t, _), items in rows.items() if t == table) for table in INGESTED_TABLES}
    return {"messages": len(messages), "files": len(rows), "rows": counts}


# ---------- Spark 연결 ----------

def topic_pattern(topics: Sequence[str]) -> str:
    """토픽 이름과 정확히 같은 것만 맞는 정규식 (Kafka 클라이언트의 Java 정규식)."""
    return "^(" + "|".join(re.escape(topic) for topic in topics) + ")$"


def kafka_options(settings: Settings, config: Config) -> dict[str, str]:
    """Spark Kafka 소스 옵션."""
    options = {
        "kafka.bootstrap.servers": settings.bootstrap,
        "kafka.security.protocol": settings.security_protocol,
        "kafka.allow.auto.create.topics": "false",       # 없는 토픽을 새로 만들지 않는다
        # 토픽 이름 목록(subscribe)으로 받으면 Kafka에 없는 토픽이 하나만 있어도 쿼리가 실패한다 (로컬 Spark 4.1.3에서 확인).
        # 이름과 정확히 같은 패턴으로 받으면 있는 토픽만 읽고, 나중에 생긴 토픽은 그때부터 읽는다
        "subscribePattern": topic_pattern(config.topics),
        "startingOffsets": config.starting_offsets,
        "maxOffsetsPerTrigger": str(config.max_offsets_per_trigger),
        # 보관 기간(3일)보다 오래 멈춰 메시지가 지워졌어도 멈추지 않고 남은 것부터 읽는다.
        # 빠진 구간은 topic_messages의 오프셋 빈틈으로 보이고 Bronze 재처리로 채운다 (설계 「신뢰성 점검」)
        "failOnDataLoss": "false",
    }
    if settings.security_protocol == "SSL":
        if settings.ssl_ca_file:
            options["kafka.ssl.truststore.type"] = "PEM"
            options["kafka.ssl.truststore.location"] = settings.ssl_ca_file
        if settings.ssl_cert_file:   # 클라이언트 인증서 (Java Kafka 클라이언트는 PEM 내용을 값으로 받는다)
            options["kafka.ssl.keystore.type"] = "PEM"
            options["kafka.ssl.keystore.certificate.chain"] = Path(settings.ssl_cert_file).read_text(encoding="utf-8")
            options["kafka.ssl.keystore.key"] = Path(settings.ssl_key_file).read_text(encoding="utf-8")
    return options


def _log(message: str) -> None:
    print(message, flush=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_query(spark, *, settings: Settings, config: Config, checker: Checker, store: Store,
                now: Callable[[], datetime] = _utc_now, log: Callable[[str], None] = _log):
    """Kafka → foreachBatch(write_batch) 스트리밍 쿼리를 시작해서 돌려준다. spark 세션 시간대는 UTC로 둔다."""
    from pyspark.sql import functions as F

    frame = (spark.readStream.format("kafka").options(**kafka_options(settings, config)).load()
             # Kafka 시각은 1970년부터의 밀리초로 받는다 (파이썬으로 옮길 때 시간대가 섞이지 않게)
             .select("topic", "partition", "offset", F.expr("unix_millis(timestamp)").alias("timestamp_ms"),
                     "key", "value"))

    def each_batch(batch, batch_id: int) -> None:
        messages = [KafkaMessage(topic=r.topic, partition=r.partition, offset=r.offset,
                                 timestamp=datetime.fromtimestamp(r.timestamp_ms / 1000, tz=timezone.utc),
                                 value=None if r.value is None else bytes(r.value),
                                 key=None if r.key is None else bytes(r.key))
                    for r in batch.collect()]
        summary = write_batch(messages, checker=checker, store=store, loaded_at=utc_naive(now()))
        log(f"적재 묶음 {batch_id}: 메시지 {summary['messages']}, 파일 {summary['files']}")

    return (frame.writeStream.foreachBatch(each_batch)
            .option("checkpointLocation", settings.checkpoint)
            .trigger(processingTime=f"{config.trigger_seconds} seconds")
            .start())
