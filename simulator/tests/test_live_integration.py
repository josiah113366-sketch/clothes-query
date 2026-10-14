import uuid
from datetime import datetime
from pathlib import Path

import pytest

from sim.common.clock import FakeTime, SimClock
from sim.common.config import ConfigError, load_config
from sim.common.control import ControlState
from sim.common.db import connect, target_host
from sim.member import params
from sim.member.baseline import run_baseline
from sim.member.live import DbStore, LiveRunner

pytestmark = pytest.mark.integration

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "db" / "schema"
START = datetime(2026, 10, 13, 9, 0, 0, tzinfo=params.KST)
SINCE = "signup_at >= '2026-10-01 00:00:00+09'"


class _Always:
    def read(self) -> ControlState:
        return ControlState(True, "normal")


@pytest.fixture
def env():
    """임시 스키마에 DDL을 적용한 (연결, DbStore 만드는 함수). 끝나면 스키마를 지운다."""
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
    conn = connect(config.database_url, schema=schema)
    for sql_file in sorted(SCHEMA_DIR.glob("*.sql")):
        conn.execute(sql_file.read_text(encoding="utf-8"))
    conn.commit()
    try:
        yield conn, lambda: DbStore(config.database_url, schema=schema)
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.commit()
        admin.close()


def _live(store: DbStore, regions, count: int) -> LiveRunner:
    clock = SimClock.fake(FakeTime(START), speed=60)
    runner = LiveRunner(
        store, regions, clock, _Always(), seed=42, max_signups=count, out=lambda _: None
    )
    runner.run()
    store.close()
    return runner


def test_live_200_after_baseline(env, regions) -> None:
    conn, make_store = env
    run_baseline(regions, 2000, 42, 1000, conn)
    runner = _live(make_store(), regions, 200)
    assert runner.summary.start_index == 0
    total, active, late, emails, phones = conn.execute(
        f"SELECT count(*) FILTER (WHERE {SINCE}), "
        f"count(*) FILTER (WHERE {SINCE} AND status = 'ACTIVE'), "
        f"count(*) FILTER (WHERE {SINCE} AND signup_at < '2026-10-13 09:00:00+09'), "
        "count(*) - count(DISTINCT email), count(*) - count(DISTINCT phone) FROM member"
    ).fetchone()
    assert (total, active, late) == (200, 200, 0)
    assert (emails, phones) == (0, 0)
    assert conn.execute("SELECT count(*) FROM member").fetchone()[0] == 2200


def test_restart_continues_from_index(env, regions) -> None:
    conn, make_store = env
    run_baseline(regions, 2000, 42, 1000, conn)
    _live(make_store(), regions, 100)
    second = _live(make_store(), regions, 100)
    assert second.summary.start_index == 100
    total, ids, phones = conn.execute(
        f"SELECT count(*), count(DISTINCT member_id), count(DISTINCT phone) "
        f"FROM member WHERE {SINCE}"
    ).fetchone()
    assert total == ids == phones == 200
    assert (
        conn.execute("SELECT count(*) - count(DISTINCT member_id) FROM member").fetchone()[0] == 0
    )


def test_one_transaction_per_signup(env, regions) -> None:
    conn, make_store = env
    run_baseline(regions, 2000, 42, 1000, conn)
    _live(make_store(), regions, 100)
    rows, xids = conn.execute(
        f"SELECT count(*), count(DISTINCT xmin::text) FROM member WHERE {SINCE}"
    ).fetchone()
    assert rows == xids == 100
