import uuid
from pathlib import Path

import pytest

from sim.common.config import ConfigError, load_config
from sim.common.db import connect, target_host
from sim.member.baseline import TableNotEmptyError, run_baseline
from sim.member.verify import run_verify

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


def test_load_2000_and_verify(conn, regions) -> None:
    summary = run_baseline(regions, 2000, 42, 1000, conn)
    assert summary.mode == "load"
    results = run_verify(conn, regions, 2000)
    assert len(results) == 12
    assert [r.number for r in results if not r.passed] == []


def test_refuses_non_empty_table(conn, regions) -> None:
    run_baseline(regions, 1000, 42, 1000, conn)
    with pytest.raises(TableNotEmptyError):
        run_baseline(regions, 1000, 42, 1000, conn)
    assert conn.execute("SELECT count(*) FROM member").fetchone()[0] == 1000
