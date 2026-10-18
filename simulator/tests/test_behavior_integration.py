"""행동 시뮬레이터 통합 테스트: 로컬 DB의 임시 스키마에 DDL을 적용해 쓰고 지운다."""

import uuid
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from behavior_fixtures import StaticCatalog, StaticMembers, first_monday

from sim.behavior.pool import DbCatalogSource, DbMemberSource
from sim.behavior.runner import BehaviorRunner
from sim.behavior.sink import DbOrderSink, MemoryClickSink, MemoryOrderSink
from sim.common.clock import FakeTime, SimClock
from sim.common.config import ConfigError, load_config
from sim.common.control import ControlState
from sim.common.db import connect, target_host
from sim.member.baseline import run_baseline

pytestmark = pytest.mark.integration

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "db" / "schema"
MONDAY = first_monday()
VISITS_DAILY = 3_000


class _Always:
    def read(self) -> ControlState:
        return ControlState(True, "normal")


@pytest.fixture
def env(regions):
    try:
        config = load_config()
    except ConfigError:
        pytest.skip("DATABASE_URL이 없습니다")
    if target_host(config.database_url) not in ("localhost", "127.0.0.1"):
        pytest.skip("로컬 DB가 아니라 건너뜁니다")
    files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not any(f.name.startswith("003") for f in files) or not any(
        f.name.startswith("004") for f in files
    ):
        pytest.skip("db/schema/003, 004가 없어 건너뜁니다")
    schema = f"test_{uuid.uuid4().hex[:8]}"
    admin = connect(config.database_url)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    admin.commit()
    conn = connect(config.database_url, schema=schema)
    for sql_file in files:
        conn.execute(sql_file.read_text(encoding="utf-8"))
    conn.commit()
    run_baseline(regions, 2_000, 42, 1_000, conn)  # 합성 회원 2,000명
    conn.execute("INSERT INTO product_design VALUES (1, 1, 't', 'g', 1, 'gg', 1, 'ig', 5900)")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO product_variant VALUES (%s, 1, 'p', 1, 'c', 1, 'a', %s)",
            [(f"{100_000_001 + i:010d}", 5_900 + 500 * (i % 60)) for i in range(1_000)],
        )
    conn.commit()
    try:
        yield config.database_url, schema, conn, admin
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.commit()
        admin.close()


def _runner(orders, members, catalog, url=None):
    clock = SimClock.fake(FakeTime(MONDAY), speed=600)
    return BehaviorRunner(
        orders,
        MemoryClickSink(),
        members,
        catalog,
        clock,
        _Always(),
        seed=42,
        run_salt=99,
        visits_daily=VISITS_DAILY,
        out=lambda _: None,
    )


def _run(runner) -> None:
    runner.run_until(MONDAY + timedelta(days=1))
    runner.drain()


def _counts(conn) -> tuple[int, int, int]:
    return tuple(
        conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("orders", "order_items", "payments")
    )


def _memory_counts(url: str, schema: str) -> tuple[int, int, int]:
    members = StaticMembers(DbMemberSource(url, schema).read_active_members())
    catalog = StaticCatalog(DbCatalogSource(url, schema).read_catalog())
    memory = MemoryOrderSink()
    _run(_runner(memory, members, catalog))
    orders = [c for c in memory.calls if c[0] == "create_order"]
    return (
        len(orders),
        sum(len(c[2]) for c in orders),
        sum(1 for c in memory.calls if c[0] == "add_payment"),
    )


CHECKS = {
    "총액 불일치": """
        SELECT o.order_id FROM orders o JOIN order_items i USING (order_id)
        GROUP BY o.order_id, o.total_amount HAVING sum(i.quantity * i.unit_price) <> o.total_amount
    """,
    "줄 없는 주문": """
        SELECT order_id FROM orders o
        WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)
    """,
    "SUCCESS 두 건 이상": """
        SELECT order_id FROM payments WHERE status = 'SUCCESS'
        GROUP BY order_id HAVING count(*) > 1
    """,
    "PAID 이상인데 SUCCESS 없음": """
        SELECT order_id FROM orders o
        WHERE status IN ('PAID', 'SHIPPED', 'DELIVERED', 'REFUNDED')
          AND NOT EXISTS (SELECT 1 FROM payments p
                          WHERE p.order_id = o.order_id AND p.status = 'SUCCESS')
    """,
    "PAYMENT_FAILED 짝": """
        SELECT order_id FROM orders o WHERE status = 'PAYMENT_FAILED'
          AND (EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id AND p.status = 'SUCCESS')
               OR NOT EXISTS (SELECT 1 FROM payments p
                              WHERE p.order_id = o.order_id AND p.status = 'FAILED'))
    """,
    "시도 번호": """
        SELECT order_id FROM payments GROUP BY order_id
        HAVING max(attempt_no) <> count(*) OR max(attempt_no) > 3
    """,
    "결제 금액": """
        SELECT p.payment_id FROM payments p JOIN orders o USING (order_id)
        WHERE p.amount <> o.total_amount
    """,
    "status_reason 짝": """
        SELECT order_id FROM orders
        WHERE (status = 'CANCELLED') <> (status_reason IS NOT DISTINCT FROM 'USER_REQUEST')
           OR (status = 'REFUNDED') <> (status_reason IS NOT DISTINCT FROM 'RETURN')
    """,
    "진행 중으로 남은 주문": """
        SELECT order_id FROM orders WHERE status IN ('PLACED', 'PAID', 'SHIPPED')
    """,
}


def test_one_day_then_drain_matches_memory_and_rules(env) -> None:
    url, schema, conn, _ = env
    orders = DbOrderSink(url, schema)
    runner = _runner(orders, DbMemberSource(url, schema), DbCatalogSource(url, schema))
    _run(runner)
    orders.close()
    counts = _counts(conn)
    assert counts[0] == runner.summary.orders > 50
    assert counts == _memory_counts(url, schema)
    for name, query in CHECKS.items():
        assert conn.execute(query).fetchall() == [], name


class _KillingSink(DbOrderSink):
    """drain 중 n번째 쓰기 직전에 자기 연결을 서버에서 끊는다."""

    def __init__(self, url: str, schema: str, admin, kill_at: set[int]) -> None:
        super().__init__(url, schema)
        self.admin, self.kill_at, self.writes, self.armed = admin, kill_at, 0, False

    def _maybe_kill(self) -> None:
        if not self.armed:
            return
        self.writes += 1
        if self.writes in self.kill_at:
            pid = self._require().info.backend_pid
            self.admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
            self.admin.commit()

    def create_order(self, order, items) -> None:
        self._maybe_kill()
        super().create_order(order, items)

    def add_payment(self, payment) -> None:
        self._maybe_kill()
        super().add_payment(payment)

    def update_order_status(self, *args) -> None:
        self._maybe_kill()
        super().update_order_status(*args)


def test_connection_killed_during_drain_loses_nothing(env) -> None:
    url, schema, conn, admin = env
    sink = _KillingSink(url, schema, admin, {3, 30, 31, 100})
    runner = _runner(sink, DbMemberSource(url, schema), DbCatalogSource(url, schema))
    runner.run_until(MONDAY + timedelta(days=1))
    sink.armed = True
    runner.drain()
    sink.close()
    assert runner.summary.reconnects == 4
    assert _counts(conn) == _memory_counts(url, schema)
    for name, query in CHECKS.items():
        assert conn.execute(query).fetchall() == [], name


def test_other_db_error_is_not_retried(env) -> None:
    url, schema, conn, _ = env
    conn.execute("DROP TABLE payments")
    conn.commit()
    runner = _runner(
        DbOrderSink(url, schema), DbMemberSource(url, schema), DbCatalogSource(url, schema)
    )
    from sim.common.db import SafeDatabaseError

    with pytest.raises(SafeDatabaseError) as info:
        _run(runner)
    assert "42P01" in str(info.value)
    assert not isinstance(info.value, psycopg.Error)
