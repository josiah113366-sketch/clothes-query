"""가짜 Store·Publisher. DB와 Kafka 없이 라우트·검증·응답 형식을 시험한다."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from clothes_api.errors import conflict, not_found, unavailable
from clothes_api.main import create_app
from clothes_api.metrics import Metrics
from clothes_api.schemas import ClickEvent, NewMember, NewOrder, NewPayment, StatusUpdate
from clothes_api.store import TRANSITIONS, MemberChange, Outcome


class FakeStore:
    def __init__(self) -> None:
        self.members: dict[UUID, NewMember] = {}
        self.inactive: set[UUID] = set()
        self.orders: dict[UUID, NewOrder] = {}
        self.status: dict[UUID, str] = {}
        self.payments: dict[UUID, NewPayment] = {}
        self.changes: list[MemberChange] = []
        self.catalog_rows: list[tuple[str, int]] = []
        self.down = False

    def ping(self) -> None:
        if self.down:
            raise unavailable("DB_UNAVAILABLE")

    def insert_member(self, member: NewMember) -> Outcome:
        existing = self.members.get(member.member_id)
        if existing is not None:
            if existing != member:
                raise conflict("ID_CONFLICT")
            return Outcome.EXISTS
        if any(m.phone == member.phone for m in self.members.values()):
            raise conflict("PHONE_TAKEN")
        self.members[member.member_id] = member
        return Outcome.CREATED

    def signup_count(self, since: datetime) -> int:
        return sum(1 for m in self.members.values() if m.signup_at >= since)

    def active_members(self, after: str | None, limit: int) -> list[UUID]:
        ids = sorted(i for i in self.members if i not in self.inactive)
        if after:
            ids = [i for i in ids if str(i) > after]
        return ids[:limit]

    def member_changes(self, since: datetime, limit: int) -> list[MemberChange]:
        return [c for c in self.changes if c.created_at >= since][:limit]

    def catalog(self, after: str | None, limit: int) -> list[tuple[str, int]]:
        rows = [r for r in self.catalog_rows if after is None or r[0] > after]
        return rows[:limit]

    def create_order(self, order: NewOrder) -> Outcome:
        if order.member_id not in self.members:
            raise not_found("MEMBER_NOT_FOUND")
        existing = self.orders.get(order.order_id)
        if existing is not None:
            if existing != order:
                raise conflict("ID_CONFLICT")
            return Outcome.EXISTS
        if order.member_id in self.inactive:
            raise conflict("MEMBER_NOT_ACTIVE")
        self.orders[order.order_id] = order
        self.status[order.order_id] = "PLACED"
        return Outcome.CREATED

    def add_payment(self, order_id: UUID, payment: NewPayment) -> Outcome:
        if order_id not in self.orders:
            raise not_found("ORDER_NOT_FOUND")
        existing = self.payments.get(payment.payment_id)
        if existing is not None:
            if existing != payment:
                raise conflict("ID_CONFLICT")
            return Outcome.EXISTS
        self.payments[payment.payment_id] = payment
        return Outcome.CREATED

    def update_status(self, order_id: UUID, update: StatusUpdate) -> Outcome:
        if order_id not in self.status:
            raise not_found("ORDER_NOT_FOUND")
        current = self.status[order_id]
        if current == update.status:
            return Outcome.EXISTS
        if update.status not in TRANSITIONS.get(current, frozenset()):
            raise conflict("INVALID_TRANSITION")
        self.status[order_id] = update.status
        return Outcome.CREATED


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[ClickEvent] = []
        self.is_ready = True
        self.fail_after: int | None = None
        self.closed = False

    def publish(self, events: Sequence[ClickEvent]) -> tuple[int, int]:
        accepted = failed = 0
        for event in events:
            if self.fail_after is not None and len(self.events) >= self.fail_after:
                failed += 1
            else:
                self.events.append(event)
                accepted += 1
        return accepted, failed

    def ready(self) -> bool:
        return self.is_ready

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def metrics() -> Metrics:
    return Metrics()


@pytest.fixture
def client(store: FakeStore, publisher: FakePublisher, metrics: Metrics):
    with TestClient(create_app(store=store, publisher=publisher, metrics=metrics)) as c:
        yield c


MEMBER_ID = "11111111-1111-4111-8111-111111111111"
ORDER_ID = "22222222-2222-4222-8222-222222222222"


def member_body(**over) -> dict:
    body = {
        "member_id": MEMBER_ID,
        "name": "홍길동",
        "email": "pii-user@example.com",
        "phone": "010-1234-5678",
        "birth_date": "1995-03-14",
        "password_hash": "hash",
        "gender": "F",
        "age_band": "20s",
        "region_sigungu": "서울특별시 강남구",
        "signup_channel": "app",
        "marketing_consent": True,
        "signup_at": "2026-10-20T06:20:01Z",
    }
    body.update(over)
    return body


def order_body(**over) -> dict:
    body = {
        "order_id": ORDER_ID,
        "member_id": MEMBER_ID,
        "session_id": "33333333-3333-4333-8333-333333333333",
        "status": "PLACED",
        "total_amount": 15800,
        "ordered_at": "2026-10-20T06:21:10Z",
        "items": [
            {
                "order_item_id": "44444444-4444-4444-8444-444444444444",
                "article_id": "0108775015",
                "quantity": 2,
                "unit_price": 7900,
            }
        ],
    }
    body.update(over)
    return body


def payment_body(**over) -> dict:
    body = {
        "payment_id": "55555555-5555-4555-8555-555555555555",
        "attempt_no": 1,
        "method": "CARD",
        "pg": "PG_A",
        "amount": 15800,
        "status": "SUCCESS",
        "failure_code": None,
        "requested_at": "2026-10-20T06:21:20Z",
        "completed_at": "2026-10-20T06:21:23Z",
    }
    body.update(over)
    return body


def click(**over) -> dict:
    body = {
        "event_id": "e-1",
        "event_type": "view",
        "member_id": MEMBER_ID,
        "article_id": "0108775015",
        "event_time": "2026-10-20T15:20:05+09:00",
        "session_id": "s-1",
    }
    body.update(over)
    return body
