import uuid
from pathlib import Path

import pyarrow as pa
import pytest
from product_fixtures import DESIGN_SCHEMA, VARIANT_SCHEMA, make_data, write_seed

from sim.common.config import ConfigError, load_config
from sim.common.db import SafeDatabaseError, connect, target_host
from sim.product import params
from sim.product.load import TableMissingError, TableNotEmptyError, run_load
from sim.product.verify import run_verify

pytestmark = pytest.mark.integration

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "db" / "schema"


@pytest.fixture
def conn():
    try:
        config = load_config()
    except ConfigError:
        pytest.skip("DATABASE_URL이 없습니다")
    if target_host(config.database_url) not in ("localhost", "127.0.0.1"):
        pytest.skip("로컬 DB가 아니라 건너뜁니다")
    schema = f"test_{uuid.uuid4().hex[:8]}"
    admin = connect(config.database_url)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    admin.commit()
    c = connect(config.database_url, schema=schema)
    for sql_file in sorted(SCHEMA_DIR.glob("*.sql")):
        c.execute(sql_file.read_text(encoding="utf-8"))
    c.commit()
    try:
        yield c
    finally:
        c.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.commit()
        admin.close()


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_load_hundreds_of_rows_and_verify_passes(conn, tmp_path) -> None:
    seed = write_seed(tmp_path, make_data(designs=150, variants_each=3))
    summary = run_load(str(seed), 100, conn)
    assert summary.rows == {params.DESIGN_TABLE: 150, params.VARIANT_TABLE: 450}
    assert count(conn, params.DESIGN_TABLE) == 150
    assert count(conn, params.VARIANT_TABLE) == 450
    results = run_verify(conn, str(seed))
    assert len(results) == 8
    assert [r.number for r in results if not r.passed] == []
    joined = conn.execute(
        "SELECT count(*) FROM product_variant v JOIN product_design d USING (product_code)"
    ).fetchone()[0]
    assert joined == 450


def test_article_id_keeps_leading_zero(conn, tmp_path) -> None:
    run_load(str(write_seed(tmp_path)), 100, conn)
    row = conn.execute(
        "SELECT min(article_id), min(length(article_id)), max(length(article_id)) FROM product_variant"
    ).fetchone()
    assert row[1] == row[2] == 10


def test_refuses_non_empty_tables(conn, tmp_path) -> None:
    seed = str(write_seed(tmp_path))
    run_load(seed, 100, conn)
    with pytest.raises(TableNotEmptyError):
        run_load(seed, 100, conn)
    assert count(conn, params.DESIGN_TABLE) == 30
    assert count(conn, params.VARIANT_TABLE) == 90


def test_refuses_when_only_design_has_rows(conn, tmp_path) -> None:
    conn.execute("INSERT INTO product_design VALUES (1, 1, 'a', 'b', 1, 'c', 1, 'd', 5900)")
    conn.commit()
    with pytest.raises(TableNotEmptyError):
        run_load(str(write_seed(tmp_path)), 100, conn)
    assert count(conn, params.DESIGN_TABLE) == 1
    assert count(conn, params.VARIANT_TABLE) == 0


def test_failure_rolls_back_both_tables(conn, tmp_path) -> None:
    data = make_data()
    data[params.VARIANT_TABLE]["product_code"][-1] = 999_999_999  # design에 없는 코드 → FK 위반
    seed = str(write_seed(tmp_path, data))
    with pytest.raises(SafeDatabaseError):
        run_load(seed, 100, conn)
    assert count(conn, params.DESIGN_TABLE) == 0
    assert count(conn, params.VARIANT_TABLE) == 0


def test_missing_tables_give_a_hint(conn, tmp_path) -> None:
    conn.execute("DROP TABLE product_variant, product_design")
    conn.commit()
    with pytest.raises(TableMissingError, match="003_product.sql"):
        run_load(str(write_seed(tmp_path)), 100, conn)


def test_schema_mismatch_inserts_nothing(conn, tmp_path) -> None:
    seed = write_seed(
        tmp_path,
        design_schema=pa.schema([f for f in DESIGN_SCHEMA if f.name != "design_price"]),
        variant_schema=VARIANT_SCHEMA,
    )
    with pytest.raises(Exception, match="design_price"):
        run_load(str(seed), 100, conn)
    assert count(conn, params.DESIGN_TABLE) == 0


def test_verify_catches_a_changed_value_in_db(conn, tmp_path) -> None:
    seed = str(write_seed(tmp_path))
    run_load(seed, 100, conn)
    conn.execute(
        "UPDATE product_design SET design_price = design_price + 500 WHERE product_code = 100003"
    )
    conn.commit()
    failed = [r.number for r in run_verify(conn, seed) if not r.passed]
    assert {7, 8} <= set(failed)
