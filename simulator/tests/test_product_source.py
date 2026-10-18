from pathlib import Path

import pyarrow as pa
import pytest
from product_fixtures import DESIGN_SCHEMA, VARIANT_SCHEMA, make_data, write_seed

from sim.product import params, source


def test_type_mapping() -> None:
    assert source.pg_type(pa.int64()) == "BIGINT"
    assert source.pg_type(pa.string()) == "TEXT"
    assert source.pg_type(pa.float64()) == "DOUBLE PRECISION"
    assert source.pg_type(pa.bool_()) == "BOOLEAN"
    assert source.pg_type(pa.timestamp("us", tz="UTC")) == "TIMESTAMPTZ"


@pytest.mark.parametrize(
    "arrow_type",
    [pa.timestamp("us"), pa.int32(), pa.list_(pa.int64()), pa.decimal128(10, 2), pa.date32()],
)
def test_unknown_type_is_an_error_not_a_guess(arrow_type: pa.DataType) -> None:
    with pytest.raises(source.UnsupportedTypeError):
        source.pg_type(arrow_type)


def test_ddl_columns_match_params() -> None:
    """params의 컬럼 목록과 테스트용 Parquet 스키마, DDL 파일이 같은 컬럼을 가진다."""
    ddl = (Path(__file__).resolve().parents[2] / "db" / "schema" / "003_product.sql").read_text(
        encoding="utf-8"
    )
    for table, schema in (
        (params.DESIGN_TABLE, DESIGN_SCHEMA),
        (params.VARIANT_TABLE, VARIANT_SCHEMA),
    ):
        assert [name for name, _ in params.COLUMNS[table]] == schema.names
        body = ddl.split(f"CREATE TABLE {table} (")[1].split(");")[0]
        for name, pg in params.COLUMNS[table]:
            line = next(line for line in body.splitlines() if line.strip().startswith(name + " "))
            assert pg.lower() in line.lower(), (table, name)
            assert "NOT NULL" in line or "PRIMARY KEY" in line


def test_matching_schema_has_no_problems() -> None:
    assert source.schema_problems(params.DESIGN_TABLE, DESIGN_SCHEMA) == []
    assert source.schema_problems(params.VARIANT_TABLE, VARIANT_SCHEMA) == []


def test_missing_extra_and_changed_columns_are_named() -> None:
    fields = [f for f in DESIGN_SCHEMA if f.name != "design_price"]
    fields[0] = pa.field("product_code", pa.string())
    fields.append(pa.field("extra_col", pa.int64()))
    problems = "\n".join(source.schema_problems(params.DESIGN_TABLE, pa.schema(fields)))
    assert "design_price" in problems and "컬럼이 없습니다" in problems
    assert "product_code" in problems and "타입이 다릅니다" in problems
    assert "extra_col" in problems and "DDL에 없는 컬럼" in problems


@pytest.mark.parametrize("name", ["detail_desc", "image_url", "name_ko", "img_path"])
def test_forbidden_columns_fail(name: str) -> None:
    schema = pa.schema([*DESIGN_SCHEMA, pa.field(name, pa.string())])
    problems = source.schema_problems(params.DESIGN_TABLE, schema)
    assert any("허용하지 않는 컬럼" in p and name in p for p in problems)


def test_unsupported_type_is_reported_with_its_column() -> None:
    schema = pa.schema([*DESIGN_SCHEMA, pa.field("created", pa.timestamp("us"))])
    assert any("created" in p for p in source.schema_problems(params.DESIGN_TABLE, schema))


def test_table_location_local_and_s3() -> None:
    assert source.table_location("/x/seed", "product_design") == "/x/seed/product_design.parquet"
    assert (
        source.table_location("s3://bucket/seed_v2/", "product_variant")
        == "s3://bucket/seed_v2/product_variant/product_variant.parquet"
    )


def test_inspect_source_reads_rows_and_batches(tmp_path) -> None:
    directory = write_seed(tmp_path, make_data(designs=10, variants_each=2))
    found = source.inspect_source(str(directory))
    assert found[params.DESIGN_TABLE].rows == 10 and found[params.VARIANT_TABLE].rows == 20
    batches = list(
        source.iter_row_batches(found[params.VARIANT_TABLE].parquet, params.VARIANT_TABLE, 7)
    )
    assert [len(b) for b in batches] == [7, 7, 6]
    assert batches[0][0][0] == f"{100_000 * 1000:010d}"  # 앞자리 0이 살아 있는 문자열
    assert len(batches[0][0]) == len(source.column_names(params.VARIANT_TABLE))


def test_inspect_source_stops_on_schema_difference(tmp_path) -> None:
    directory = write_seed(
        tmp_path, design_schema=pa.schema([f for f in DESIGN_SCHEMA if f.name != "design_price"])
    )
    with pytest.raises(source.SourceError, match="design_price"):
        source.inspect_source(str(directory))


def test_missing_file_is_a_clear_error(tmp_path) -> None:
    with pytest.raises(source.SourceError, match="파일이 없습니다"):
        source.inspect_source(str(tmp_path))
