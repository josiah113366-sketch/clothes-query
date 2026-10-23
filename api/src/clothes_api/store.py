"""DB 접근. 라우트는 Store 프로토콜만 본다(테스트는 가짜 Store를 쓴다).

멱등: 같은 ID로 다시 오면 저장된 내용과 비교해 같으면 EXISTS, 다르면 ID_CONFLICT.
DB 오류는 sqlstate·제약 이름으로만 분류한다. 값(PII)을 오류 메시지에 싣지 않는다.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from clothes_api.errors import ApiError, conflict, not_found, unavailable, unprocessable
from clothes_api.schemas import NewMember, NewOrder, NewPayment, StatusUpdate

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"

# 허용 전이 (시뮬레이터 behavior/payment.py next_transition, behavior/runner.py와 같다)
TRANSITIONS: dict[str, frozenset[str]] = {
    "PLACED": frozenset({"PAID", "PAYMENT_FAILED", "CANCELLED"}),
    "PAID": frozenset({"SHIPPED", "CANCELLED"}),
    "SHIPPED": frozenset({"DELIVERED"}),
    "DELIVERED": frozenset({"REFUNDED"}),
}

MEMBER_COLUMNS = (
    "member_id", "name", "email", "phone", "birth_date", "password_hash", "gender",
    "age_band", "region_sigungu", "signup_channel", "marketing_consent", "signup_at",
)  # fmt: skip


class Outcome(Enum):
    CREATED = 201
    EXISTS = 200


@dataclass(frozen=True)
class MemberChange:
    member_id: UUID
    created_at: datetime


class Store(Protocol):
    def ping(self) -> None: ...

    def insert_member(self, member: NewMember) -> Outcome: ...

    def signup_count(self, since: datetime) -> int: ...

    def active_members(self, after: str | None, limit: int) -> list[UUID]: ...

    def member_changes(self, since: datetime, limit: int) -> list[MemberChange]: ...

    def catalog(self, after: str | None, limit: int) -> list[tuple[str, int]]: ...

    def create_order(self, order: NewOrder) -> Outcome: ...

    def add_payment(self, order_id: UUID, payment: NewPayment) -> Outcome: ...

    def update_status(self, order_id: UUID, update: StatusUpdate) -> Outcome: ...


def _constraint(error: psycopg.Error) -> str:
    diag = getattr(error, "diag", None)
    return (getattr(diag, "constraint_name", None) or "") if diag else ""


def _same_time(a: datetime, b: datetime) -> bool:
    return a == b  # 둘 다 시간대가 있는 값이라 같은 순간이면 같다


class PgStore:
    def __init__(self, pool: ConnectionPool, timeout: float) -> None:
        self._pool = pool
        self._timeout = timeout

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection]:
        try:
            with self._pool.connection(timeout=self._timeout) as conn:
                yield conn
        except PoolTimeout:
            raise unavailable("DB_BUSY", "DB 연결을 기다리다 시간이 지났습니다") from None
        except psycopg.OperationalError:
            raise unavailable("DB_UNAVAILABLE", "DB에 연결할 수 없습니다") from None

    def ping(self) -> None:
        with self._conn() as conn:
            conn.execute("SELECT 1")

    # --- 회원 ---

    def insert_member(self, member: NewMember) -> Outcome:
        values = member.model_dump()
        columns = ", ".join(MEMBER_COLUMNS)
        placeholders = ", ".join(f"%({c})s" for c in MEMBER_COLUMNS)
        with self._conn() as conn:
            try:
                row = conn.execute(
                    f"INSERT INTO members ({columns}, status) VALUES ({placeholders}, 'ACTIVE') "
                    "ON CONFLICT (member_id) DO NOTHING RETURNING member_id",
                    values,
                ).fetchone()
            except psycopg.errors.UniqueViolation as error:
                name = _constraint(error)
                if "phone" in name:
                    raise conflict("PHONE_TAKEN", "phone이 이미 쓰이고 있습니다") from None
                if "email" in name:
                    raise conflict("EMAIL_TAKEN", "email이 이미 쓰이고 있습니다") from None
                raise conflict("UNIQUE_VIOLATION", name) from None
            except psycopg.errors.CheckViolation as error:
                raise unprocessable("CHECK_VIOLATION", _constraint(error)) from None
            if row:
                return Outcome.CREATED
            stored = conn.execute(
                f"SELECT {columns} FROM members WHERE member_id = %s", (member.member_id,)
            ).fetchone()
        if stored is None or not self._member_equal(values, stored):
            raise conflict("ID_CONFLICT", f"member_id {member.member_id}의 내용이 다릅니다")
        return Outcome.EXISTS

    @staticmethod
    def _member_equal(values: dict, stored: Sequence) -> bool:
        for column, saved in zip(MEMBER_COLUMNS, stored, strict=True):
            sent = values[column]
            if isinstance(sent, datetime):
                if not _same_time(sent, saved):
                    return False
            elif sent != saved:
                return False
        return True

    def signup_count(self, since: datetime) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT count(*) FROM members WHERE signup_at >= %s", (since,)
            ).fetchone()
        return int(row[0]) if row else 0

    def active_members(self, after: str | None, limit: int) -> list[UUID]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT member_id FROM members WHERE status = 'ACTIVE' "
                "AND (%(after)s::uuid IS NULL OR member_id > %(after)s::uuid) "
                "ORDER BY member_id LIMIT %(limit)s",
                {"after": after, "limit": limit},
            ).fetchall()
        return [r[0] for r in rows]

    def member_changes(self, since: datetime, limit: int) -> list[MemberChange]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT member_id, created_at FROM members WHERE status = 'ACTIVE' "
                "AND created_at >= %s ORDER BY created_at, member_id LIMIT %s",
                (since, limit),
            ).fetchall()
        return [MemberChange(r[0], r[1]) for r in rows]

    def catalog(self, after: str | None, limit: int) -> list[tuple[str, int]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT article_id, price FROM product_variant "
                "WHERE (%(after)s::text IS NULL OR article_id > %(after)s::text) "
                "ORDER BY article_id LIMIT %(limit)s",
                {"after": after, "limit": limit},
            ).fetchall()
        return [(r[0], int(r[1])) for r in rows]

    # --- 주문 ---

    def create_order(self, order: NewOrder) -> Outcome:
        with self._conn() as conn:
            try:
                with conn.transaction():
                    member = conn.execute(
                        "SELECT status FROM members WHERE member_id = %s FOR SHARE",
                        (order.member_id,),
                    ).fetchone()
                    if member is None:
                        raise not_found("MEMBER_NOT_FOUND", f"member_id {order.member_id}")
                    inserted = conn.execute(
                        "INSERT INTO orders (order_id, member_id, session_id, status, "
                        "status_reason, total_amount, ordered_at, updated_at) "
                        "VALUES (%s, %s, %s, 'PLACED', NULL, %s, %s, %s) "
                        "ON CONFLICT (order_id) DO NOTHING RETURNING order_id",
                        (order.order_id, order.member_id, order.session_id,
                         order.total_amount, order.ordered_at, order.ordered_at),
                    ).fetchone()  # fmt: skip
                    if inserted is None:
                        return self._order_exists(conn, order)
                    if member[0] != "ACTIVE":
                        raise conflict("MEMBER_NOT_ACTIVE", f"member_id {order.member_id}")
                    with conn.cursor() as cur:
                        cur.executemany(
                            "INSERT INTO order_items (order_item_id, order_id, article_id, "
                            "quantity, unit_price) VALUES (%s, %s, %s, %s, %s)",
                            [(i.order_item_id, order.order_id, i.article_id, i.quantity,
                              i.unit_price) for i in order.items],
                        )  # fmt: skip
            except psycopg.errors.ForeignKeyViolation as error:
                raise unprocessable("UNKNOWN_REFERENCE", _constraint(error)) from None
            except psycopg.errors.UniqueViolation as error:
                raise conflict("ID_CONFLICT", _constraint(error)) from None
            except psycopg.errors.CheckViolation as error:
                raise unprocessable("CHECK_VIOLATION", _constraint(error)) from None
        return Outcome.CREATED

    @staticmethod
    def _order_exists(conn: psycopg.Connection, order: NewOrder) -> Outcome:
        """이미 있는 주문: 만들 때의 값(상태 제외)과 항목이 같으면 EXISTS."""
        head = conn.execute(
            "SELECT member_id, session_id, total_amount, ordered_at FROM orders "
            "WHERE order_id = %s",
            (order.order_id,),
        ).fetchone()
        items = conn.execute(
            "SELECT order_item_id, article_id, quantity, unit_price FROM order_items "
            "WHERE order_id = %s ORDER BY order_item_id",
            (order.order_id,),
        ).fetchall()
        sent_items = sorted(
            (i.order_item_id, i.article_id, i.quantity, i.unit_price) for i in order.items
        )
        same = (
            head is not None
            and (head[0], head[1], head[2]) == (order.member_id, order.session_id,
                                                order.total_amount)
            and _same_time(head[3], order.ordered_at)
            and [tuple(r) for r in items] == sent_items
        )  # fmt: skip
        if not same:
            raise conflict("ID_CONFLICT", f"order_id {order.order_id}의 내용이 다릅니다")
        return Outcome.EXISTS

    def add_payment(self, order_id: UUID, payment: NewPayment) -> Outcome:
        values = (
            payment.payment_id, order_id, payment.attempt_no, payment.method, payment.pg,
            payment.amount, payment.status, payment.failure_code, payment.requested_at,
            payment.completed_at,
        )  # fmt: skip
        with self._conn() as conn:
            try:
                with conn.transaction():
                    if (
                        conn.execute(
                            "SELECT 1 FROM orders WHERE order_id = %s", (order_id,)
                        ).fetchone()
                        is None
                    ):
                        raise not_found("ORDER_NOT_FOUND", f"order_id {order_id}")
                    row = conn.execute(
                        "INSERT INTO payments (payment_id, order_id, attempt_no, method, pg, "
                        "amount, status, failure_code, requested_at, completed_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (payment_id) DO NOTHING RETURNING payment_id",
                        values,
                    ).fetchone()
                    if row:
                        return Outcome.CREATED
                    stored = conn.execute(
                        "SELECT payment_id, order_id, attempt_no, method, pg, amount, status, "
                        "failure_code, requested_at, completed_at FROM payments "
                        "WHERE payment_id = %s",
                        (payment.payment_id,),
                    ).fetchone()
            except psycopg.errors.UniqueViolation as error:
                # 같은 (order_id, attempt_no)에 다른 payment_id
                raise conflict("ID_CONFLICT", _constraint(error)) from None
            except psycopg.errors.CheckViolation as error:
                raise unprocessable("CHECK_VIOLATION", _constraint(error)) from None
        if (
            stored is None
            or tuple(stored[:8]) != values[:8]
            or not (_same_time(stored[8], values[8]) and _same_time(stored[9], values[9]))
        ):
            raise conflict("ID_CONFLICT", f"payment_id {payment.payment_id}의 내용이 다릅니다")
        return Outcome.EXISTS

    def update_status(self, order_id: UUID, update: StatusUpdate) -> Outcome:
        with self._conn() as conn:
            try:
                with conn.transaction():
                    row = conn.execute(
                        "SELECT status, ordered_at FROM orders WHERE order_id = %s FOR UPDATE",
                        (order_id,),
                    ).fetchone()
                    if row is None:
                        raise not_found("ORDER_NOT_FOUND", f"order_id {order_id}")
                    current, ordered_at = row
                    if current == update.status:
                        return Outcome.EXISTS  # 재시도: 이미 그 상태다
                    if update.status not in TRANSITIONS.get(current, frozenset()):
                        raise conflict(
                            "INVALID_TRANSITION", f"{current} → {update.status}은 허용되지 않습니다"
                        )
                    if update.updated_at < ordered_at:
                        raise unprocessable("CHECK_VIOLATION", "updated_at < ordered_at")
                    conn.execute(
                        "UPDATE orders SET status = %s, status_reason = %s, updated_at = %s "
                        "WHERE order_id = %s",
                        (update.status, update.status_reason, update.updated_at, order_id),
                    )
            except psycopg.errors.CheckViolation as error:
                raise unprocessable("CHECK_VIOLATION", _constraint(error)) from None
        return Outcome.CREATED


__all__ = ["ApiError", "MemberChange", "Outcome", "PgStore", "Store", "TRANSITIONS"]
