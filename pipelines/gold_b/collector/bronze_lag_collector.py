"""Bronze 지연 수집기: S3 Sink 커넥터가 Kafka 메시지를 얼마나 밀려서 처리하는지 잰다.

한 번 실행(run_once)할 때 하는 일
  1. 측정 시각(collected_at, UTC)을 정한다.
  2. Kafka Connect에 커넥터 상태를 묻는다. 대상 토픽은 GOLD_B_LAG_TOPICS, 없으면 커넥터 설정의 topics다.
  3. Kafka에 토픽·파티션별로 S3 Sink 소비자 그룹이 처리한 위치(committed_offset)와 마지막 위치(end_offset)를 묻는다.
  4. lag_msgs = end_offset - committed_offset
     lag_sec  = 처리 안 된 가장 오래된 메시지(처리한 위치의 메시지)의 Kafka 시각부터 측정 시각까지(초)
  5. 토픽 x 파티션 줄을 Parquet 파일 하나로 <저장 위치>/dt=YYYY-MM-DD/hour=HH/ 에 쓴다 (로컬 폴더 또는 s3://).

읽기만 한다. 메시지는 밀린 파티션마다 1건만 읽어 시각만 쓰고, S3 Sink의 처리 위치는 바꾸지 않는다.
규칙·환경변수·실행 방법은 같은 폴더의 README.md에 있다.

실행 (저장소 루트에서):
  python -m pipelines.gold_b.collector.bronze_lag_collector --once
  python -m pipelines.gold_b.collector.bronze_lag_collector --interval 60
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

# gold_b.bronze_lag_snapshots 컬럼 (pipelines/gold_b/ddl/bronze_lag_snapshots.sql과 같은 순서)
COLUMNS = ("collected_at", "topic", "kafka_partition", "end_offset", "committed_offset",
           "lag_msgs", "lag_sec", "connector_state")

DEFAULT_BOOTSTRAP = "localhost:29092"          # 시뮬레이터 로컬 Kafka
DEFAULT_CONNECT_URL = "http://localhost:8083"  # 시뮬레이터 로컬 Connect
DEFAULT_CONNECTOR = "bronze-s3-sink"
SECURITY_PROTOCOLS = ("PLAINTEXT", "SSL")
ADDRESS_FAMILIES = ("any", "v4", "v6")         # librdkafka broker.address.family
TIMEOUT_SEC = 10.0

# connector_state에 수집기가 붙이는 값 (나머지는 Connect가 주는 RUNNING, PAUSED, FAILED 등)
UNREACHABLE = "UNREACHABLE"   # Connect REST에 접속하지 못함
NOT_FOUND = "NOT_FOUND"       # 그 이름의 커넥터가 없음


class ConfigError(ValueError):
    """환경변수가 잘못됐다."""


class CollectorError(RuntimeError):
    """이번 측정을 끝내지 못했다. 메시지에 주소·버킷 이름을 넣지 않는다."""


class TopicMissing(Exception):
    """Kafka에 그 토픽이 없다."""


class ConnectorNotFound(Exception):
    """Connect에 그 이름의 커넥터가 없다."""


class ConnectUnavailable(Exception):
    """Connect REST에 접속하지 못했거나 응답을 읽지 못했다."""


@dataclass(frozen=True)
class Settings:
    """환경변수로 받는 설정. 주소·경로는 repr에 나오지 않게 한다 (로그에 남지 않게)."""

    output: str = field(repr=False)
    bootstrap: str = field(default=DEFAULT_BOOTSTRAP, repr=False)
    security_protocol: str = "PLAINTEXT"
    address_family: str = "any"
    ssl_ca_file: str = field(default="", repr=False)
    ssl_cert_file: str = field(default="", repr=False)
    ssl_key_file: str = field(default="", repr=False)
    connect_url: str = field(default=DEFAULT_CONNECT_URL, repr=False)
    connector: str = DEFAULT_CONNECTOR
    group: str = ""
    topics: tuple[str, ...] = ()

    @property
    def sink_group(self) -> str:
        """S3 Sink 소비자 그룹. Kafka Connect는 sink 커넥터마다 connect-<커넥터 이름> 그룹을 쓴다."""
        return self.group or f"connect-{self.connector}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        def get(key: str) -> str:
            return (env.get(key) or "").strip()

        output = get("GOLD_B_LAG_OUTPUT")
        if not output:
            raise ConfigError("GOLD_B_LAG_OUTPUT(저장 위치)이 필요합니다")
        protocol = (get("KAFKA_SECURITY_PROTOCOL") or "PLAINTEXT").upper()
        if protocol not in SECURITY_PROTOCOLS:
            raise ConfigError(f"KAFKA_SECURITY_PROTOCOL은 {', '.join(SECURITY_PROTOCOLS)} 중 하나여야 합니다")
        family = (get("KAFKA_ADDRESS_FAMILY") or "any").lower()
        if family not in ADDRESS_FAMILIES:
            raise ConfigError(f"KAFKA_ADDRESS_FAMILY는 {', '.join(ADDRESS_FAMILIES)} 중 하나여야 합니다")
        cert, key = get("KAFKA_SSL_CERT_FILE"), get("KAFKA_SSL_KEY_FILE")
        if bool(cert) != bool(key):
            raise ConfigError("KAFKA_SSL_CERT_FILE과 KAFKA_SSL_KEY_FILE은 함께 설정해야 합니다")
        connect_url = (get("GOLD_B_CONNECT_URL") or DEFAULT_CONNECT_URL).rstrip("/")
        if not connect_url.startswith(("http://", "https://")):
            raise ConfigError("GOLD_B_CONNECT_URL은 http:// 또는 https://로 시작해야 합니다")
        return cls(
            output=output,
            bootstrap=get("KAFKA_BOOTSTRAP") or DEFAULT_BOOTSTRAP,
            security_protocol=protocol,
            address_family=family,
            ssl_ca_file=get("KAFKA_SSL_CA_FILE"),
            ssl_cert_file=cert,
            ssl_key_file=key,
            connect_url=connect_url,
            connector=get("GOLD_B_SINK_CONNECTOR") or DEFAULT_CONNECTOR,
            group=get("GOLD_B_SINK_GROUP"),
            topics=tuple(t.strip() for t in get("GOLD_B_LAG_TOPICS").split(",") if t.strip()),
        )


def read_env_file(path: str | Path) -> dict[str, str]:
    """KEY=VALUE 줄로 된 .env 파일을 읽는다 (# 주석과 빈 줄은 건너뜀). 값은 출력하지 않는다."""
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


# ---------- 바깥(Kafka, Connect)과 만나는 곳. 시험에서는 가짜로 바꾼다 ----------

class KafkaView(Protocol):
    def partitions(self, topic: str) -> list[int]: ...
    def committed(self, group: str, topic: str, partitions: list[int]) -> dict[int, int | None]: ...
    def watermarks(self, topic: str, partition: int) -> tuple[int, int]: ...
    def timestamps(self, wanted: Mapping[tuple[str, int], int]) -> dict[tuple[str, int], datetime | None]: ...
    def close(self) -> None: ...


class ConnectView(Protocol):
    def status(self, connector: str) -> Mapping: ...
    def topics(self, connector: str) -> list[str]: ...


def _quiet_logger() -> logging.Logger:
    """librdkafka 내부 로그를 버리는 로거. 그 로그에는 브로커 주소가 들어 있다 (시뮬레이터와 같은 방식)."""
    logger = logging.getLogger("gold_b.lag_collector.librdkafka")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def kafka_config(settings: Settings) -> dict[str, object]:
    config: dict[str, object] = {
        "bootstrap.servers": settings.bootstrap,
        "security.protocol": settings.security_protocol,
        "logger": _quiet_logger(),
    }
    if settings.address_family != "any":
        # Windows 로컬에서 localhost가 IPv6(::1)로 먼저 붙어 그룹 처리 위치 조회가 _TRANSPORT로 실패할 때 v4로 고정한다
        config["broker.address.family"] = settings.address_family
    if settings.security_protocol == "SSL":
        for key, value in (("ssl.ca.location", settings.ssl_ca_file),
                           ("ssl.certificate.location", settings.ssl_cert_file),
                           ("ssl.key.location", settings.ssl_key_file)):
            if value:
                config[key] = value
    return config


class KafkaClient:
    """Kafka 관리 API와 소비자로 위치·메시지 시각을 읽는다. 처리 위치를 커밋하지 않는다."""

    def __init__(self, config: Mapping[str, object], timeout: float = TIMEOUT_SEC):
        from confluent_kafka import Consumer
        from confluent_kafka.admin import AdminClient

        self._timeout = timeout
        # 토픽 정보를 물을 때 없는 토픽이 자동으로 생기지 않게 한다 (시뮬레이터와 같은 설정)
        self._admin = AdminClient({**config, "allow.auto.create.topics": False})
        self._consumer = Consumer({
            **config,
            # 시각만 읽는 임시 그룹. assign만 쓰므로 그룹에 들어가지 않고 커밋도 하지 않는다
            "group.id": f"gold-b-lag-{uuid.uuid4().hex}",
            "enable.auto.commit": False,
            "enable.partition.eof": False,
            "allow.auto.create.topics": False,
            # 읽으려던 메시지가 그 사이 지워졌으면 남아 있는 가장 오래된 메시지부터 (규칙 2)
            "auto.offset.reset": "earliest",
            # 파티션마다 1건만 필요하다
            "max.partition.fetch.bytes": 65536,
        })

    def partitions(self, topic: str) -> list[int]:
        metadata = self._admin.list_topics(topic=topic, timeout=self._timeout).topics.get(topic)
        if metadata is None or metadata.error is not None or not metadata.partitions:
            raise TopicMissing(topic)
        return sorted(metadata.partitions)

    def committed(self, group: str, topic: str, partitions: list[int]) -> dict[int, int | None]:
        from confluent_kafka import ConsumerGroupTopicPartitions, TopicPartition

        request = [ConsumerGroupTopicPartitions(group, [TopicPartition(topic, p) for p in partitions])]
        result = self._admin.list_consumer_group_offsets(request, request_timeout=self._timeout)[group].result()
        found: dict[int, int | None] = {p: None for p in partitions}
        for tp in result.topic_partitions or []:
            if tp.error is None and tp.offset >= 0:   # 처리 기록이 없으면 음수(OFFSET_INVALID)
                found[tp.partition] = tp.offset
        return found

    def watermarks(self, topic: str, partition: int) -> tuple[int, int]:
        from confluent_kafka import TopicPartition

        offsets = self._consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=self._timeout)
        if offsets is None:
            raise CollectorError(f"마지막 위치를 읽지 못했습니다: {topic}[{partition}]")
        low, high = offsets
        return low, high

    def timestamps(self, wanted: Mapping[tuple[str, int], int]) -> dict[tuple[str, int], datetime | None]:
        from confluent_kafka import TIMESTAMP_NOT_AVAILABLE, TopicPartition

        found: dict[tuple[str, int], datetime | None] = {key: None for key in wanted}
        if not wanted:
            return found
        self._consumer.assign([TopicPartition(t, p, offset) for (t, p), offset in wanted.items()])
        remaining = set(wanted)
        deadline = time.monotonic() + self._timeout
        try:
            while remaining and time.monotonic() < deadline:
                message = self._consumer.poll(0.5)
                if message is None or message.error() is not None:
                    continue
                key = (message.topic(), message.partition())
                if key not in remaining:
                    continue
                kind, millis = message.timestamp()
                if kind != TIMESTAMP_NOT_AVAILABLE and millis >= 0:
                    found[key] = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
                remaining.discard(key)
                self._consumer.pause([TopicPartition(*key)])   # 그 파티션은 더 읽지 않는다
        finally:
            self._consumer.unassign()
        return found

    def close(self) -> None:
        self._consumer.close()


class ConnectClient:
    """Kafka Connect REST에서 커넥터 상태와 설정을 읽는다 (표준 라이브러리 urllib만 씀)."""

    def __init__(self, base_url: str, timeout: float = TIMEOUT_SEC):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _get(self, path: str) -> dict:
        request = Request(self._base + path, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                raise ConnectorNotFound() from None
            raise ConnectUnavailable(f"HTTP {exc.code}") from None
        except (URLError, OSError, ValueError) as exc:     # 접속 실패, 시간 초과, JSON이 아님
            raise ConnectUnavailable(type(exc).__name__) from None

    def status(self, connector: str) -> dict:
        return self._get(f"/connectors/{quote(connector, safe='')}/status")

    def topics(self, connector: str) -> list[str]:
        config = self._get(f"/connectors/{quote(connector, safe='')}/config")
        return [t.strip() for t in str(config.get("topics", "")).split(",") if t.strip()]


# ---------- 계산 (바깥을 모르는 순수 함수) ----------

def connector_state(status: Mapping) -> str:
    """커넥터 상태. 태스크가 RUNNING이 아니면 그 태스크 상태가 더 직접적인 신호라 그것을 쓴다 (규칙 3)."""
    state = str((status.get("connector") or {}).get("state") or "UNKNOWN")
    for task in status.get("tasks") or []:
        task_state = task.get("state")
        if task_state != "RUNNING":
            return str(task_state or "UNKNOWN")
    return state


def oldest_unprocessed_offset(low: int, end: int, committed: int | None) -> int | None:
    """처리 안 된 가장 오래된 메시지의 위치. 보관 기간으로 지워졌으면 남아 있는 가장 오래된 위치 (규칙 2)."""
    if committed is None or committed >= end:
        return None
    start = max(committed, low)
    return start if start < end else None


def make_row(collected_at: datetime, topic: str, partition: int, end: int, committed: int | None,
             oldest_at: datetime | None, state: str) -> dict:
    if committed is None:               # 규칙 1: 처리 기록이 없으면 비운다
        lag_msgs = lag_sec = None
    else:
        lag_msgs = max(end - committed, 0)
        if lag_msgs == 0:
            lag_sec = 0.0
        elif oldest_at is None:         # 시각을 모름 (남은 메시지가 없거나 읽지 못함)
            lag_sec = None
        else:                           # 시계가 조금 어긋나도 음수가 되지 않게
            lag_sec = max((collected_at - oldest_at).total_seconds(), 0.0)
    return {"collected_at": collected_at, "topic": topic, "kafka_partition": partition,
            "end_offset": end, "committed_offset": committed, "lag_msgs": lag_msgs,
            "lag_sec": lag_sec, "connector_state": state}


def connector_info(settings: Settings, connect: ConnectView) -> tuple[str, tuple[str, ...]]:
    """(커넥터 상태, 잴 토픽 목록). Connect가 안 돼도 GOLD_B_LAG_TOPICS가 있으면 계속 잰다."""
    try:
        state = connector_state(connect.status(settings.connector))
    except ConnectorNotFound:
        state = NOT_FOUND
    except ConnectUnavailable:
        state = UNREACHABLE
    topics = settings.topics
    if not topics:
        if state in (NOT_FOUND, UNREACHABLE):
            raise CollectorError("대상 토픽을 알 수 없습니다. GOLD_B_LAG_TOPICS를 설정하세요")
        try:
            topics = tuple(connect.topics(settings.connector))
        except (ConnectorNotFound, ConnectUnavailable) as exc:
            raise CollectorError("커넥터 설정에서 대상 토픽을 읽지 못했습니다") from exc
    if not topics:
        raise CollectorError("대상 토픽이 비어 있습니다")
    return state, topics


def collect_once(settings: Settings, kafka: KafkaView, connect: ConnectView,
                 collected_at: datetime) -> tuple[list[dict], list[str]]:
    """(측정한 줄, Kafka에 없어서 건너뛴 토픽). Kafka에 접속하지 못하면 예외를 그대로 올린다 (규칙 3)."""
    state, topics = connector_info(settings, connect)
    measured: list[tuple[str, int, int, int | None]] = []
    wanted: dict[tuple[str, int], int] = {}
    skipped: list[str] = []
    for topic in topics:
        try:
            partitions = kafka.partitions(topic)
        except TopicMissing:
            skipped.append(topic)
            continue
        # 처리 위치를 먼저, 마지막 위치를 나중에 읽는다. 그 사이에 기록이 새로 생겨도 처리 위치가 마지막 위치를 넘지 않는다
        committed = kafka.committed(settings.sink_group, topic, partitions)
        for partition in partitions:
            low, end = kafka.watermarks(topic, partition)
            done = committed.get(partition)
            measured.append((topic, partition, end, done))
            offset = oldest_unprocessed_offset(low, end, done)
            if offset is not None:
                wanted[(topic, partition)] = offset
    if not measured:
        raise CollectorError("잴 수 있는 토픽이 없습니다")
    stamps = kafka.timestamps(wanted) if wanted else {}
    rows = [make_row(collected_at, topic, partition, end, done, stamps.get((topic, partition)), state)
            for topic, partition, end, done in measured]
    return rows, skipped


# ---------- 저장 ----------

def write_rows(rows: list[dict], output: str, collected_at: datetime) -> str:
    """줄을 Parquet 파일 하나로 시간 폴더에 쓰고, 저장 위치 아래의 상대 경로를 돌려준다."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([
        ("collected_at", pa.timestamp("us")), ("topic", pa.string()), ("kafka_partition", pa.int32()),
        ("end_offset", pa.int64()), ("committed_offset", pa.int64()), ("lag_msgs", pa.int64()),
        ("lag_sec", pa.float64()), ("connector_state", pa.string()),
    ])
    utc = collected_at.astimezone(timezone.utc)
    table = pa.Table.from_pylist(
        [{**row, "collected_at": row["collected_at"].astimezone(timezone.utc).replace(tzinfo=None)} for row in rows],
        schema=schema,
    )
    relative = (f"dt={utc:%Y-%m-%d}/hour={utc:%H}/"
                f"part-{utc:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}.parquet")
    if output.startswith("s3://"):
        import boto3

        bucket, _, prefix = output[len("s3://"):].partition("/")
        buffer = pa.BufferOutputStream()
        pq.write_table(table, buffer, compression="snappy")
        key = "/".join(part for part in (prefix.strip("/"), relative) if part)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buffer.getvalue().to_pybytes())
    else:
        target = Path(output) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # '.'으로 시작하는 임시 이름에 쓰고 바꾼다. Athena는 '.'·'_'로 시작하는 파일을 읽지 않는다
        temp = target.with_name(f".{target.name}.tmp")
        pq.write_table(table, temp, compression="snappy")
        os.replace(temp, target)
    return relative


# ---------- 실행 ----------

def _log(message: str) -> None:
    print(message, flush=True)


def _error_label(exc: BaseException) -> str:
    """예외 종류만 짧게. Kafka·네트워크 오류 메시지에는 주소가 들어 있을 수 있어 내용은 쓰지 않는다."""
    if exc.args and hasattr(exc.args[0], "name"):
        try:
            return f"{type(exc).__name__}({exc.args[0].name()})"
        except Exception:  # noqa: BLE001 - 이름을 못 얻으면 종류만
            pass
    return type(exc).__name__


def run_once(settings: Settings, kafka: KafkaView | None = None, connect: ConnectView | None = None,
             now: datetime | None = None, log: Callable[[str], None] = _log) -> bool:
    """한 번 재서 저장한다. 실패하면 파일을 쓰지 않고 False."""
    collected_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    client = kafka
    try:
        if client is None:
            client = KafkaClient(kafka_config(settings))
        rows, skipped = collect_once(settings, client, connect or ConnectClient(settings.connect_url), collected_at)
        written = write_rows(rows, settings.output, collected_at)
    except CollectorError as exc:
        log(f"측정 실패: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - Kafka 접속 실패 등. 줄을 쓰지 않고 끝낸다 (규칙 3)
        log(f"측정 실패: {_error_label(exc)}")
        return False
    finally:
        if kafka is None and client is not None:
            client.close()
    lags = [row["lag_sec"] for row in rows if row["lag_sec"] is not None]
    log(f"기록: {written} (줄 {len(rows)}개, 커넥터 {rows[0]['connector_state']}, "
        f"가장 큰 lag_sec {max(lags) if lags else '없음'})")
    if skipped:
        log(f"건너뛴 토픽 (Kafka에 없음): {', '.join(skipped)}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bronze 지연 수집기: S3 Sink가 Kafka 메시지를 얼마나 밀려서 처리하는지 잰다.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="한 번 재고 끝낸다 (기본, CronJob용)")
    mode.add_argument("--interval", type=int, metavar="초", help="이 간격(초)마다 계속 잰다 (예: 60, 상시 실행용)")
    parser.add_argument("--env-file", metavar="경로",
                        help="KEY=VALUE 설정 파일. 같은 이름의 환경변수가 있으면 환경변수를 쓴다")
    args = parser.parse_args(argv)
    try:
        file_values = read_env_file(args.env_file) if args.env_file else {}
        settings = Settings.from_env({**file_values, **os.environ})
    except OSError:
        print("설정 오류: --env-file 파일을 읽지 못했습니다", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    if args.interval is None:
        return 0 if run_once(settings) else 1
    if args.interval < 1:
        print("설정 오류: --interval은 1 이상이어야 합니다", file=sys.stderr)
        return 2
    try:
        while True:
            started = time.monotonic()
            run_once(settings)
            time.sleep(max(args.interval - (time.monotonic() - started), 0.0))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
