"""데이터 오염 통합 테스트: 로컬 DB의 임시 스키마에 DDL을 적용해 쓰고 지운다."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sim.common.config import ConfigError, load_config
from sim.common.db import SafeDatabaseError, connect, target_host
from sim.controller import pollution as pollution_module
from sim.controller.model import DUPLICATE_SUCCESS_PAYMENT, ORDER_TOTAL_MISMATCH
from sim.controller.pollution import DbPollution, PollutionError
from sim.member.baseline import run_baseline

pytestmark = pytest.mark.integration

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "db" / "schema"
T0 = datetime(2026, 10, 18, 0, 0, 0, tzinfo=UTC)
# (상태, 결제 결과들) — 순서대로 ordered_at이 1분씩 늦다 (뒤가 최신)
ORDERS = [
    ("DELIVERED", ["SUCCESS"]),
    ("PAYMENT_FAILED", ["FAILED"]),
    ("SHIPPED", ["FAILED", "SUCCESS"]),
    ("PLACED", []),
    ("PAID", ["SUCCESS"]),
    ("PAID", ["SUCCESS"]),
]


@pytest.fixture
def env(regions):
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
    run_baseline(regions, 20, 42, 1_000, conn)
    try:
        yield config.database_url, schema, conn
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.commit()
        admin.close()


def _seed_orders(conn) -> list[str]:
    member = str(conn.execute("SELECT member_id FROM members LIMIT 1").fetchone()[0])
    conn.execute("INSERT INTO product_design VALUES (1, 1, 't', 'g', 1, 'gg', 1, 'ig', 5900)")
    conn.execute("INSERT INTO product_variant VALUES ('0100000001', 1, 'p', 1, 'c', 1, 'a', 5900)")
    ids = []
    for i, (status, attempts) in enumerate(ORDERS):
        order_id, at = str(uuid.uuid4()), T0 + timedelta(minutes=i)
        ids.append(order_id)
        conn.execute(
            "INSERT INTO orders VALUES (%s, %s, %s, %s, NULL, 11800, %s, %s)",
            (order_id, member, str(uuid.uuid4()), status, at, at + timedelta(seconds=30)),
        )
        conn.execute(
            "INSERT INTO order_items VALUES (%s, %s, '0100000001', 2, 5900)",
            (str(uuid.uuid4()), order_id),
        )
        for n, result in enumerate(attempts, start=1):
            code = None if result == "SUCCESS" else "INSUFFICIENT_BALANCE"
            done = at + timedelta(seconds=10 * n)
            conn.execute(
                "INSERT INTO payments VALUES (%s, %s, %s, 'CARD', 'PG_A', 11800, %s, %s, %s, %s)",
                (str(uuid.uuid4()), order_id, n, result, code, done - timedelta(seconds=2), done),
            )
    conn.commit()
    return ids


MISMATCH_SQL = """
    SELECT o.order_id::text FROM orders o JOIN order_items i USING (order_id)
    GROUP BY o.order_id, o.total_amount HAVING sum(i.quantity * i.unit_price) <> o.total_amount
"""
DOUBLE_SUCCESS_SQL = """
    SELECT order_id::text FROM payments WHERE status = 'SUCCESS'
    GROUP BY order_id HAVING count(*) > 1
"""


def test_order_total_mismatch(env) -> None:
    url, schema, conn = env
    ids = _seed_orders(conn)
    result = DbPollution(url, 42, schema).apply(ORDER_TOTAL_MISMATCH, 3, "inc-1")
    assert result.affected_count == 3
    assert list(result.order_ids) == [ids[5], ids[4], ids[2]]  # PAID 이후 상태 중 최근 순
    assert sorted(r[0] for r in conn.execute(MISMATCH_SQL).fetchall()) == sorted(result.order_ids)
    totals = dict(conn.execute("SELECT order_id::text, total_amount FROM orders").fetchall())
    assert all(totals[o] == 21_800 for o in result.order_ids)
    # updated_at은 건드리지 않는다
    assert (
        conn.execute(
            "SELECT count(*) FROM orders WHERE updated_at <> ordered_at + interval '30 seconds'"
        ).fetchone()[0]
        == 0
    )


def test_duplicate_success_payment(env) -> None:
    url, schema, conn = env
    ids = _seed_orders(conn)
    result = DbPollution(url, 42, schema).apply(DUPLICATE_SUCCESS_PAYMENT, 3, "inc-2")
    assert list(result.order_ids) == [ids[5], ids[4], ids[2]]
    assert sorted(r[0] for r in conn.execute(DOUBLE_SUCCESS_SQL).fetchall()) == sorted(
        result.order_ids
    )
    rows = conn.execute(
        "SELECT order_id::text, attempt_no FROM payments WHERE order_id::text = %s ORDER BY attempt_no",
        (ids[2],),
    ).fetchall()
    assert [r[1] for r in rows] == [
        1,
        2,
        3,
    ]  # 최대 시도 번호 + 1, (order_id, attempt_no) 유니크 유지
    amounts = conn.execute(
        "SELECT DISTINCT amount, method, pg FROM payments WHERE order_id::text = ANY(%s) AND status = 'SUCCESS'",
        (list(result.order_ids),),
    ).fetchall()
    assert amounts == [(11800, "CARD", "PG_A")]


def test_check_reads_only_and_fails_without_targets(env) -> None:
    url, schema, conn = env
    with pytest.raises(PollutionError):
        DbPollution(url, 42, schema).check(ORDER_TOTAL_MISMATCH, 5)
    _seed_orders(conn)
    assert DbPollution(url, 42, schema).check(ORDER_TOTAL_MISMATCH, 30) == 4
    assert DbPollution(url, 42, schema).check(DUPLICATE_SUCCESS_PAYMENT, 2) == 2
    assert conn.execute(MISMATCH_SQL).fetchall() == []  # 읽기만 했다


def test_failure_mid_transaction_changes_nothing(env, monkeypatch) -> None:
    url, schema, conn = env
    _seed_orders(conn)
    monkeypatch.setattr(
        pollution_module, "pollution_payment_id", lambda *a: "00000000-0000-0000-0000-000000000001"
    )
    with pytest.raises(SafeDatabaseError) as info:  # 두 번째 행에서 PK 위반
        DbPollution(url, 42, schema).apply(DUPLICATE_SUCCESS_PAYMENT, 3, "inc-3")
    assert "23505" in str(info.value)
    assert conn.execute(DOUBLE_SUCCESS_SQL).fetchall() == []
    assert conn.execute("SELECT count(*) FROM payments").fetchone()[0] == 6
