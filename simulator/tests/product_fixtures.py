"""상품 테스트용 작은 Parquet. 실제 시드 파일은 쓰지 않는다."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from sim.product import params

DESIGN_SCHEMA = pa.schema(
    [
        ("product_code", pa.int64()),
        ("product_type_no", pa.int64()),
        ("product_type_name", pa.string()),
        ("product_group_name", pa.string()),
        ("garment_group_no", pa.int64()),
        ("garment_group_name", pa.string()),
        ("index_group_no", pa.int64()),
        ("index_group_name", pa.string()),
        ("design_price", pa.int64()),
    ]
)
VARIANT_SCHEMA = pa.schema(
    [
        ("article_id", pa.string()),
        ("product_code", pa.int64()),
        ("prod_name", pa.string()),
        ("colour_group_code", pa.int64()),
        ("colour_group_name", pa.string()),
        ("graphical_appearance_no", pa.int64()),
        ("graphical_appearance_name", pa.string()),
        ("price", pa.int64()),
    ]
)


def make_data(designs: int = 30, variants_each: int = 3) -> dict[str, dict[str, list]]:
    """컬럼별 목록. 가격은 5,900부터 500원 단위, article_id는 앞자리 0이 있는 10자리 문자열이다."""
    design = {name: [] for name in DESIGN_SCHEMA.names}
    variant = {name: [] for name in VARIANT_SCHEMA.names}
    for d in range(designs):
        code = 100_000 + d
        price = 5_900 + 500 * (d % 40)
        for key, value in zip(
            DESIGN_SCHEMA.names,
            (
                code,
                d % 5,
                f"type{d % 5}",
                f"group{d % 3}",
                d % 4,
                f"garment{d % 4}",
                1,
                "Ladieswear",
                price,
            ),
            strict=True,
        ):
            design[key].append(value)
        for v in range(variants_each):
            for key, value in zip(
                VARIANT_SCHEMA.names,
                (
                    f"{code * 1000 + v:010d}",
                    code,
                    f"name{d}",
                    v,
                    f"colour{v}",
                    v % 2,
                    f"look{v % 2}",
                    price,
                ),
                strict=True,
            ):
                variant[key].append(value)
    return {params.DESIGN_TABLE: design, params.VARIANT_TABLE: variant}


def write_seed(
    directory: Path,
    data: dict[str, dict[str, list]] | None = None,
    design_schema: pa.Schema = DESIGN_SCHEMA,
    variant_schema: pa.Schema = VARIANT_SCHEMA,
) -> Path:
    data = data or make_data()
    directory.mkdir(parents=True, exist_ok=True)
    for table, schema in (
        (params.DESIGN_TABLE, design_schema),
        (params.VARIANT_TABLE, variant_schema),
    ):
        table_data = pa.table({name: data[table][name] for name in schema.names}, schema=schema)
        pq.write_table(table_data, directory / f"{table}.parquet")
    return directory
