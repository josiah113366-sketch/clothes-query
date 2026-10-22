"""로컬 Docker Postgres(·Kafka)로 PgStore와 발행을 확인한다.

simulator/docker-compose.yml의 Postgres(`localhost:5432`, DB clothes)를 쓴다. 기존 테이블을 건드리지
않도록 테스트마다 임시 스키마를 만들고 db/schema DDL을 적용한 뒤 지운다.
로컬 주소가 아니거나 닿지 않으면 건너뛴다.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import ConnectionPool

from clothes_api.errors import ApiError
from clothes_api.schemas import NewMember, NewOrder, NewPayment, StatusUpdate
from clothes_api.store import Outcome, PgStore

pytestmark = pytest.mark.integration

LOCAL_URL = "postgresql://sim:sim@localhost:5432/clothes"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "db" / "schema"
T0 = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)


def _url() -> str:
    url = os.environ.get("API_TEST_DATABASE_URL", LOCAL_URL)
    if "localhost" not in url and "127.0.0.1" not in url:
        pytest.skip("로컬 DB가 아니다")
    return url


@pytest.fixture
def schema():
    url = _url()
    name = f"api_it_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("로컬 Postgres에 닿지 않는다 (docker compose up -d)")
    with admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
        for ddl in sorted(SCHEMA_DIR.glob("*.sql")):
            admin.execute(ddl.read_text(encoding="utf-8"))
        admin.execute("INSERT INTO product_design VALUES (1, 1, 't', 'g', 1, 'gg', 1, 'ig', 7900)")
        admin.execute(
            "INSERT INTO product_variant VALUES ('0108775015', 1, 'n', 1, 'c', 1, 'ga', 7900)"
        )
    yield url, name
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture
def store(schema):
    url, name = schema
    pool = ConnectionPool(
        url, min_size=1, max_size=2, kwargs={"options": f"-c search_path={name}"}, open=True
    )
    yield PgStore(pool, timeout=2.0)
    pool.close()


def _member(i: int = 1, phone: str | None = None) -> NewMember:
    return NewMember(
        member_id=UUID(int=i),
        name="테스트",
        email=f"user{i}@example.com",
        phone=phone or f"010-0000-{i:04d}",
        birth_date="1990-01-01",
        password_hash="h",
        gender="F",
        age_band="30s",
        region_sigungu="서울특별시 중구",
        signup_channel="web",
        marketing_consent=True,
        signup_at=T0,
    )


def _order(member: int = 1, total: int = 15800) -> NewOrder:
    return NewOrder(
        order_id=UUID(int=1000),
        member_id=UUID(int=member),
        session_id=UUID(int=2000),
        total_amount=total,
        ordered_at=T0 + timedelta(minutes=1),
        items=[
            {
                "order_item_id": UUID(int=3000),
                "article_id": "0108775015",
                "quantity": 2,
                "unit_price": total // 2,
            }
        ],
    )


def _payment(**over) -> NewPayment:
    data = {
        "payment_id": UUID(int=4000),
        "attempt_no": 1,
        "method": "CARD",
        "pg": "PG_A",
        "amount": 15800,
        "status": "SUCCESS",
        "requested_at": T0 + timedelta(minutes=2),
        "completed_at": T0 + timedelta(minutes=2, seconds=3),
    }
    data.update(over)
    return NewPayment(**data)


def _code(call) -> str:
    with pytest.raises(ApiError) as info:
        call()
    return info.value.code


def test_member_insert_idempotent_and_conflicts(store):
    assert store.insert_member(_member()) is Outcome.CREATED
    assert store.insert_member(_member()) is Outcome.EXISTS
    assert _code(lambda: store.insert_member(_member().model_copy(update={"gender": "M"}))) == (
        "ID_CONFLICT"
    )
    assert _code(lambda: store.insert_member(_member(2, phone="010-0000-0001"))) == "PHONE_TAKEN"
    assert store.signup_count(T0) == 1 and store.signup_count(T0 + timedelta(seconds=1)) == 0
    assert store.active_members(None, 10) == [UUID(int=1)]
    changes = store.member_changes(datetime(2000, 1, 1, tzinfo=UTC), 10)
    assert [c.member_id for c in changes] == [UUID(int=1)]


def test_order_transaction_and_rules(store):
    store.insert_member(_member())
    assert store.create_order(_order()) is Outcome.CREATED
    assert store.create_order(_order()) is Outcome.EXISTS
    assert _code(lambda: store.create_order(_order(total=15802))) == "ID_CONFLICT"
    unknown = _order().model_copy(
        update={"order_id": UUID(int=1001), "items": [_order().items[0].model_copy(
            update={"order_item_id": UUID(int=3001), "article_id": "9999999999"})]}
    )  # fmt: skip
    assert _code(lambda: store.create_order(unknown)) == "UNKNOWN_REFERENCE"
    # 항목 INSERT가 실패하면 주문도 남지 않는다(한 트랜잭션)
    with store._conn() as conn:
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 1


def test_member_not_active(store, schema):
    url, name = schema
    store.insert_member(_member())
    with psycopg.connect(url, autocommit=True, options=f"-c search_path={name}") as conn:
        conn.execute(
            "UPDATE members SET status = 'WITHDRAWN', withdrawn_at = %s WHERE member_id = %s",
            (T0 + timedelta(days=1), UUID(int=1)),
        )
    assert _code(lambda: store.create_order(_order())) == "MEMBER_NOT_ACTIVE"
    assert store.active_members(None, 10) == []


def test_payment_and_status(store):
    store.insert_member(_member())
    store.create_order(_order())
    oid = UUID(int=1000)
    assert store.add_payment(oid, _payment()) is Outcome.CREATED
    assert store.add_payment(oid, _payment()) is Outcome.EXISTS
    other = _payment(payment_id=UUID(int=4001))  # 같은 attempt_no, 다른 id
    assert _code(lambda: store.add_payment(oid, other)) == "ID_CONFLICT"
    assert _code(lambda: store.add_payment(UUID(int=9), _payment())) == "ORDER_NOT_FOUND"
    paid = StatusUpdate(status="PAID", updated_at=T0 + timedelta(minutes=3))
    assert store.update_status(oid, paid) is Outcome.CREATED
    assert store.update_status(oid, paid) is Outcome.EXISTS
    refund = StatusUpdate(status="REFUNDED", status_reason="RETURN", updated_at=T0)
    assert _code(lambda: store.update_status(oid, refund)) == "INVALID_TRANSITION"
    early = StatusUpdate(status="SHIPPED", updated_at=T0)
    assert _code(lambda: store.update_status(oid, early)) == "CHECK_VIOLATION"


def test_catalog(store):
    assert store.catalog(None, 10) == [("0108775015", 7900)]
    assert store.catalog("0108775015", 10) == []


def test_kafka_publish_roundtrip():
    """로컬 Kafka(localhost:29092)의 임시 토픽에 발행해 키·값을 확인한다."""
    from confluent_kafka import Consumer
    from confluent_kafka.admin import AdminClient, NewTopic

    from clothes_api.config import KafkaSettings
    from clothes_api.kafka import KafkaClickPublisher
    from clothes_api.metrics import Metrics
    from clothes_api.schemas import ClickEvent

    bootstrap = os.environ.get("API_TEST_KAFKA", "localhost:29092")
    admin = AdminClient({"bootstrap.servers": bootstrap})
    try:
        admin.list_topics(timeout=3)
    except Exception:
        pytest.skip("로컬 Kafka에 닿지 않는다 (docker compose --profile cdc up -d kafka)")
    topic = f"api-it-{uuid.uuid4().hex[:8]}"
    admin.create_topics([NewTopic(topic, 1, 1)])[topic].result(10)
    try:
        publisher = KafkaClickPublisher(KafkaSettings(bootstrap=bootstrap), topic, Metrics())
        event = ClickEvent(
            event_id="e-1",
            event_type="view",
            member_id="m",
            article_id="a",
            event_time="2026-10-20T15:00:00+09:00",
            session_id="s-1",
        )
        assert publisher.publish([event]) == (1, 0)
        assert publisher.ready() is True
        publisher.close()
        consumer = Consumer(
            {"bootstrap.servers": bootstrap, "group.id": topic, "auto.offset.reset": "earliest"}
        )
        consumer.subscribe([topic])
        message = None
        for _ in range(30):
            message = consumer.poll(1)
            if message is not None and message.error() is None:
                break
        consumer.close()
        assert message is not None and message.key() == b"s-1"
        assert b'"event_time":"2026-10-20T06:00:00Z"' in message.value()
    finally:
        admin.delete_topics([topic])
