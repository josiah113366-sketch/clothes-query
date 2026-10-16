"""상품 시드 Parquet 읽기. 로컬 디렉터리 또는 s3:// 주소를 받는다. S3는 읽기만 한다."""

import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from sim.product import params


class SourceError(RuntimeError):
    """원본을 읽을 수 없거나 스키마가 DDL과 다를 때. 메시지에 값(상품 이름 등)을 담지 않는다."""


class UnsupportedTypeError(SourceError):
    pass


def is_s3(source: str) -> bool:
    return source.startswith(params.S3_SCHEME)


def table_location(source: str, table: str) -> str:
    """로컬은 <디렉터리>/<테이블>.parquet, S3는 <접두사>/<테이블>/<테이블>.parquet 이다."""
    if is_s3(source):
        return f"{source.rstrip('/')}/{table}/{table}.parquet"
    return str(Path(source) / f"{table}.parquet")


def _read_s3(location: str) -> bytes:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError

    bucket, _, key = location.removeprefix(params.S3_SCHEME).partition("/")
    timeout = params.S3_READ_TIMEOUT_SECONDS
    client = boto3.client(
        "s3",
        region_name=params.S3_REGION,
        config=Config(connect_timeout=timeout, read_timeout=timeout, retries={"max_attempts": 2}),
    )
    try:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as error:  # 응답 본문은 쓰지 않고 오류 코드만 남긴다
        code = error.response.get("Error", {}).get("Code", "unknown")
        raise SourceError(f"S3에서 읽지 못했습니다: {location} (오류 코드 {code})") from None
    except BotoCoreError as error:
        raise SourceError(f"S3에서 읽지 못했습니다: {location} ({type(error).__name__})") from None


def open_parquet(source: str, table: str) -> pq.ParquetFile:
    location = table_location(source, table)
    try:
        if is_s3(source):
            return pq.ParquetFile(io.BytesIO(_read_s3(location)))
        if not Path(location).is_file():
            raise SourceError(f"파일이 없습니다: {location}")
        return pq.ParquetFile(location)
    except (pa.ArrowInvalid, pa.ArrowIOError, OSError) as error:
        raise SourceError(
            f"Parquet 파일을 읽지 못했습니다: {location} ({type(error).__name__})"
        ) from None


def pg_type(arrow_type: pa.DataType) -> str:
    """Parquet 타입을 PostgreSQL 타입으로 바꾼다. 정해 두지 않은 타입은 오류다."""
    if pa.types.is_int64(arrow_type):
        return "BIGINT"
    if pa.types.is_string(arrow_type):
        return "TEXT"
    if pa.types.is_float64(arrow_type):
        return "DOUBLE PRECISION"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_timestamp(arrow_type) and arrow_type.tz is not None:
        return "TIMESTAMPTZ"
    raise UnsupportedTypeError(f"정해 두지 않은 Parquet 타입입니다: {arrow_type}")


def schema_problems(table: str, schema: pa.Schema) -> list[str]:
    """Parquet 스키마가 DDL(params)과 다른 곳을 모두 돌려준다. 없으면 빈 목록이다."""
    problems: list[str] = []
    expected = dict(params.COLUMNS[table])
    actual: dict[str, str] = {}
    for field in schema:
        lowered = field.name.lower()
        if any(part in lowered for part in params.FORBIDDEN_NAME_PARTS):
            problems.append(f"허용하지 않는 컬럼(설명문·이미지·현지화 계열): {field.name}")
            continue
        try:
            actual[field.name] = pg_type(field.type)
        except UnsupportedTypeError as error:
            problems.append(f"{field.name}: {error}")
    for name in expected:
        if name not in actual and not any(f"{name}:" in p for p in problems):
            problems.append(f"컬럼이 없습니다: {name}")
    for name, pg in actual.items():
        if name not in expected:
            problems.append(f"DDL에 없는 컬럼입니다: {name} ({pg})")
        elif expected[name] != pg:
            problems.append(f"타입이 다릅니다: {name} (Parquet→{pg}, DDL {expected[name]})")
    return problems


@dataclass
class TableSource:
    table: str
    parquet: pq.ParquetFile
    rows: int


def inspect_source(source: str) -> dict[str, TableSource]:
    """두 파일을 열고 스키마를 DDL과 비교한다. 다른 곳이 있으면 모아서 한 번에 알린다."""
    found: dict[str, TableSource] = {}
    problems: list[str] = []
    for table in params.TABLES:
        parquet = open_parquet(source, table)
        problems += [f"{table}: {p}" for p in schema_problems(table, parquet.schema_arrow)]
        found[table] = TableSource(table, parquet, parquet.metadata.num_rows)
    if problems:
        raise SourceError("스키마가 DDL과 다릅니다.\n  " + "\n  ".join(problems))
    return found


def column_names(table: str) -> list[str]:
    return [name for name, _ in params.COLUMNS[table]]


def iter_row_batches(
    parquet: pq.ParquetFile, table: str, batch_size: int
) -> Iterator[list[tuple[object, ...]]]:
    """DDL 컬럼 순서로 행을 배치(튜플 목록)로 돌려준다. 한 번에 batch_size행만 메모리에 둔다."""
    names = column_names(table)
    for batch in parquet.iter_batches(batch_size=batch_size, columns=names):
        data = batch.to_pydict()
        yield list(zip(*(data[name] for name in names), strict=True))


def read_columns(parquet: pq.ParquetFile, table: str) -> dict[str, list]:
    """컬럼별 파이썬 목록으로 전부 읽는다 (verify용. 상품은 십수만 행이라 메모리에 올려도 된다)."""
    return parquet.read(columns=column_names(table)).to_pydict()
