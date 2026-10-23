"""Gold B 원장 공통 도구: 표별 Parquet 스키마, 시간 폴더, 메시지 하나의 원장 줄, 파일 저장소(로컬 폴더·S3).

재처리 잡이 쓰고, 적재 잡(4단계)과 파일 합치기(6단계)도 같은 것을 쓴다.
표 정의의 원본은 ddl/*.sql이다. 여기 스키마가 DDL과 같은지는 tests/test_reprocess.py가 확인한다.

시각은 모두 UTC다. 줄과 파일 안에서는 시간대 표시가 없는 값(naive datetime)으로 다룬다 (DDL의 TIMESTAMP).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Mapping, Protocol, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

# ddl/*.sql과 같은 순서·타입
TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "payment_events": (
        ("payment_id", "STRING"), ("order_id", "STRING"), ("attempt_no", "INT"), ("pg", "STRING"),
        ("status", "STRING"), ("failure_code", "STRING"), ("completed_at", "TIMESTAMP"),
        ("payment_content_hash", "STRING"), ("fingerprint_version", "STRING"),
        ("kafka_partition", "INT"), ("kafka_offset", "BIGINT"), ("loaded_at", "TIMESTAMP"),
    ),
    "topic_messages": (
        ("topic", "STRING"), ("kafka_partition", "INT"), ("kafka_offset", "BIGINT"),
        ("kafka_timestamp", "TIMESTAMP"), ("loaded_at", "TIMESTAMP"),
    ),
    "bronze_lag_snapshots": (
        ("collected_at", "TIMESTAMP"), ("topic", "STRING"), ("kafka_partition", "INT"),
        ("end_offset", "BIGINT"), ("committed_offset", "BIGINT"), ("lag_msgs", "BIGINT"),
        ("lag_sec", "DOUBLE"), ("connector_state", "STRING"),
    ),
    "malformed_events": (
        ("topic", "STRING"), ("kafka_partition", "INT"), ("kafka_offset", "BIGINT"),
        ("kafka_timestamp", "TIMESTAMP"), ("field", "STRING"), ("reason", "STRING"),
        ("raw_sample", "STRING"), ("rule_version", "STRING"), ("loaded_at", "TIMESTAMP"),
    ),
    "reprocess_events": (
        ("request_id", "STRING"), ("step", "STRING"), ("at", "TIMESTAMP"), ("actor", "STRING"),
        ("reason", "STRING"), ("window_start", "TIMESTAMP"), ("window_end", "TIMESTAMP"),
        ("rule_version", "STRING"), ("source", "STRING"), ("attempt", "INT"),
        ("parent_request_id", "STRING"), ("detail", "STRING"),
    ),
}
_ARROW_TYPES = {"STRING": pa.string(), "INT": pa.int32(), "BIGINT": pa.int64(),
                "DOUBLE": pa.float64(), "TIMESTAMP": pa.timestamp("us")}
SCHEMAS = {table: pa.schema([(name, _ARROW_TYPES[kind]) for name, kind in columns])
           for table, columns in TABLE_COLUMNS.items()}

# 시간 폴더를 나누는 이벤트 시각 (reprocess_events는 폴더 없음)
EVENT_TIME = {"payment_events": "completed_at", "topic_messages": "kafka_timestamp",
              "malformed_events": "kafka_timestamp", "bronze_lag_snapshots": "collected_at"}
HOUR = timedelta(hours=1)

# 형식 검사가 결제 메시지에서 돌려주는 업무 칼럼과 오류 하나의 칸
PAYMENT_FIELDS = ("payment_id", "order_id", "attempt_no", "pg", "status", "failure_code",
                  "completed_at", "payment_content_hash", "fingerprint_version")
ERROR_FIELDS = ("field", "reason", "raw_sample")


# ---------- 시각과 시간 폴더 ----------

def utc_naive(value: datetime) -> datetime:
    """시간대가 있으면 UTC로 바꾸고 표시를 뗀다. 없으면 이미 UTC로 본다."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def hour_of(value: datetime) -> datetime:
    """그 시각이 들어가는 시간 폴더의 시작 (UTC)."""
    return utc_naive(value).replace(minute=0, second=0, microsecond=0)


def hour_folder(table: str, hour: datetime) -> str:
    """저장 위치 아래 시간 폴더의 상대 경로. 예: payment_events/dt=2026-10-21/hour=06"""
    return f"{table}/dt={hour:%Y-%m-%d}/hour={hour:%H}"


# ---------- 메시지 하나 → 원장 줄 ----------

@dataclass(frozen=True)
class KafkaMessage:
    topic: str
    partition: int
    offset: int
    timestamp: datetime      # Kafka 시각 (UTC)
    value: bytes | None
    key: bytes | None = None

    @property
    def position(self) -> tuple[str, int, int]:
        return (self.topic, self.partition, self.offset)


@dataclass(frozen=True)
class Judgement:
    """형식 검사 결과. payment: 결제 원장에 넣을 업무 칼럼(PAYMENT_FIELDS, 오류 없는 결제만). errors: 오류 하나 = 칸 하나(ERROR_FIELDS)."""

    payment: Mapping[str, object] | None = None
    errors: Sequence[Mapping[str, object]] = ()


class Checker(Protocol):
    """형식 검사 함수 (2단계에서 만듦). 적재 잡과 재처리 잡이 같은 것을 쓴다."""

    rule_version: str   # format_rules.yaml의 version

    def __call__(self, message: KafkaMessage) -> Judgement: ...


def message_rows(message: KafkaMessage, judgement: Judgement, rule_version: str,
                 loaded_at: datetime) -> dict[str, list[dict]]:
    """메시지 하나의 원장 줄. Kafka 위치·loaded_at·rule_version은 여기서 붙인다 (형식 검사는 판정만 한다)."""
    kafka_timestamp = utc_naive(message.timestamp)
    where = {"kafka_partition": message.partition, "kafka_offset": message.offset}
    rows: dict[str, list[dict]] = {
        "topic_messages": [{"topic": message.topic, **where, "kafka_timestamp": kafka_timestamp,
                            "loaded_at": loaded_at}],
        "payment_events": [],
        "malformed_events": [],
    }
    if judgement.payment is not None:
        if judgement.errors:
            raise ValueError("오류가 있는 메시지는 결제 원장에 넣지 않는다")
        payment = {name: judgement.payment.get(name) for name in PAYMENT_FIELDS}
        if not isinstance(payment["completed_at"], datetime):
            raise ValueError("결제 줄에 completed_at이 없다 (시간 폴더를 정할 수 없음)")
        payment["completed_at"] = utc_naive(payment["completed_at"])
        rows["payment_events"].append({**payment, **where, "loaded_at": loaded_at})
    fields_seen: set[object] = set()
    for error in judgement.errors:
        # 설계 「중복 제거」: (토픽, 파티션, offset, rule_version, field)가 같으면 한 줄만. 같은 필드의 첫 오류를 남긴다
        if error.get("field") in fields_seen:
            continue
        fields_seen.add(error.get("field"))
        rows["malformed_events"].append({
            "topic": message.topic, **where, "kafka_timestamp": kafka_timestamp,
            **{name: error.get(name) for name in ERROR_FIELDS},
            "rule_version": rule_version, "loaded_at": loaded_at})
    return rows


# ---------- 파일 저장소 ----------

class Store(Protocol):
    """원장 파일을 읽고 쓰는 곳. 경로는 저장 위치(예: s3://<버킷>/gold_b) 아래의 상대 경로다.

    files()는 기본으로 우리 잡이 쓴 .parquet 파일만 돌려준다. any_name=True면 확장자와 상관없이
    Athena가 읽는 파일을 모두 돌려준다 (Athena INSERT INTO가 쓴 파일은 이름에 확장자가 없을 수 있다).
    """

    def files(self, folder: str, any_name: bool = False) -> list[str]: ...
    def read(self, path: str, table: str) -> list[dict]: ...
    def write(self, path: str, table: str, rows: Sequence[Mapping],
              metadata: Mapping[str, str] | None = None) -> None: ...
    def metadata(self, path: str) -> dict[str, str]: ...
    def delete(self, paths: Sequence[str]) -> None: ...


def _visible_parquet(name: str) -> bool:
    # Athena는 '.'·'_'로 시작하는 파일을 읽지 않는다 (임시 파일, _SUCCESS)
    return name.endswith(".parquet") and not name.startswith((".", "_"))


def _visible_any(name: str) -> bool:
    """확장자와 상관없이 Athena가 읽는 파일. 숨김·임시 파일과 S3 폴더 표시는 뺀다."""
    return not name.startswith((".", "_")) and not name.endswith((".tmp", "$folder$"))


def _visible(name: str, any_name: bool) -> bool:
    return _visible_any(name) if any_name else _visible_parquet(name)


def to_arrow(table: str, rows: Sequence[Mapping], metadata: Mapping[str, str] | None = None) -> pa.Table:
    """metadata는 Parquet 파일에 함께 적는 짧은 글 (예: 파일 합치기가 합친 원래 파일 목록)."""
    schema = SCHEMAS[table]
    data = pa.Table.from_pylist([{name: row.get(name) for name in schema.names} for row in rows], schema=schema)
    return data.replace_schema_metadata(dict(metadata)) if metadata else data


def _decode(metadata) -> dict[str, str]:
    return {key.decode(): value.decode() for key, value in (metadata or {}).items()}


def from_arrow(table: str, data: pa.Table) -> list[dict]:
    """파일을 그 표의 스키마로 맞춰 읽는다. 시각 형식(마이크로초, 나노초, 시간대 표시)이 달라도 UTC naive로 맞춘다."""
    schema = SCHEMAS[table]
    columns = []
    for target in schema:
        if target.name in data.column_names:
            column = data.column(target.name)
            columns.append(column if column.type == target.type else column.cast(target.type, safe=False))
        else:
            columns.append(pa.nulls(data.num_rows, target.type))
    return pa.Table.from_arrays(columns, schema=schema).to_pylist()


class LocalStore:
    """로컬 폴더 (시험·로컬 확인용)."""

    def __init__(self, root: str | Path):
        self._root = Path(root)

    def __repr__(self) -> str:
        return "LocalStore(...)"

    def files(self, folder: str, any_name: bool = False) -> list[str]:
        directory = self._root / folder
        if not directory.is_dir():
            return []
        return sorted(f"{folder}/{item.name}" for item in directory.iterdir()
                      if item.is_file() and _visible(item.name, any_name))

    def read(self, path: str, table: str) -> list[dict]:
        return from_arrow(table, pq.read_table(self._root / path))

    def write(self, path: str, table: str, rows: Sequence[Mapping],
              metadata: Mapping[str, str] | None = None) -> None:
        target = self._root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # '.'으로 시작하는 임시 이름에 다 쓴 뒤 바꾼다. 쓰는 도중의 파일을 Athena가 읽지 않는다
        temp = target.with_name(f".{target.name}.tmp")
        pq.write_table(to_arrow(table, rows, metadata), temp, compression="snappy")
        os.replace(temp, target)

    def metadata(self, path: str) -> dict[str, str]:
        return _decode(pq.read_schema(self._root / path).metadata)

    def delete(self, paths: Sequence[str]) -> None:
        for path in paths:
            (self._root / path).unlink(missing_ok=True)


class S3Store:
    """S3 (boto3). 자격 증명은 boto3 기본 방식(EKS Pod Identity, 환경변수 등)으로 읽는다."""

    def __init__(self, location: str, client=None):
        bucket, _, prefix = location[len("s3://"):].partition("/")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._s3 = client

    def __repr__(self) -> str:   # 버킷 이름을 로그에 남기지 않는다
        return "S3Store(...)"

    def _key(self, path: str) -> str:
        return f"{self._prefix}/{path}" if self._prefix else path

    def files(self, folder: str, any_name: bool = False) -> list[str]:
        start = self._key(folder) + "/"
        found = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=start):
            for item in page.get("Contents", []):
                name = item["Key"][len(start):]
                if name and "/" not in name and _visible(name, any_name):
                    found.append(f"{folder}/{name}")
        return sorted(found)

    def read(self, path: str, table: str) -> list[dict]:
        body = self._s3.get_object(Bucket=self._bucket, Key=self._key(path))["Body"].read()
        return from_arrow(table, pq.read_table(pa.BufferReader(body)))

    def write(self, path: str, table: str, rows: Sequence[Mapping],
              metadata: Mapping[str, str] | None = None) -> None:
        buffer = pa.BufferOutputStream()
        pq.write_table(to_arrow(table, rows, metadata), buffer, compression="snappy")
        self._s3.put_object(Bucket=self._bucket, Key=self._key(path), Body=buffer.getvalue().to_pybytes())

    def metadata(self, path: str) -> dict[str, str]:
        body = self._s3.get_object(Bucket=self._bucket, Key=self._key(path))["Body"].read()
        return _decode(pq.read_schema(pa.BufferReader(body)).metadata)

    def delete(self, paths: Sequence[str]) -> None:
        keys = [self._key(path) for path in paths]
        for i in range(0, len(keys), 1000):   # 한 번에 1000개까지
            response = self._s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": key} for key in keys[i:i + 1000]], "Quiet": True})
            if response.get("Errors"):
                raise RuntimeError(f"S3 파일 {len(response['Errors'])}개를 지우지 못했다")


def open_store(location: str) -> Store:
    """s3://<버킷>/<접두어> 이면 S3, 아니면 로컬 폴더."""
    return S3Store(location) if location.startswith("s3://") else LocalStore(location)
