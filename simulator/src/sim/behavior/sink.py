"""출력 자리. 주문 Sink(지금은 DB 직접 쓰기)와 클릭 Sink(지금은 파일 또는 버림).

나중에 쇼핑몰 API(ApiOrderSink)나 Kafka(클릭)로 바꿀 때 같은 인터페이스를 구현해 끼운다.
DB 오류(psycopg.Error)는 그대로 던진다. 재연결과 오류 가리기는 실행기가 한다.
"""

import json
from collections.abc import Sequence
from dataclasses import astuple, fields
from datetime import datetime
from pathlib import Path
from typing import Protocol, TextIO

import psycopg
from psycopg import sql

from sim.behavior.model import ClickEvent, NewOrder, NewOrderItem, NewPayment
from sim.common.timezone import KST


class OrderSink(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...

    def create_order(self, order: NewOrder, items: Sequence[NewOrderItem]) -> None:
        """orders 1행 + order_items N행을 한 트랜잭션으로."""
        ...

    def add_payment(self, payment: NewPayment) -> None: ...

    def update_order_status(
        self, order_id: str, status: str, status_reason: str | None, updated_at: datetime
    ) -> None: ...


class ClickSink(Protocol):
    def publish(self, event: ClickEvent) -> None: ...

    def close(self) -> None: ...


def _insert(table: str, cls: type) -> sql.Composed:
    columns = [f.name for f in fields(cls)]
    return sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )


ORDER_INSERT = _insert("orders", NewOrder)
ITEM_INSERT = _insert("order_items", NewOrderItem)
PAYMENT_INSERT = _insert("payments", NewPayment)
STATUS_UPDATE = sql.SQL(
    "UPDATE orders SET status = %s, status_reason = %s, updated_at = %s WHERE order_id = %s"
)


class DbOrderSink:
    """자동 커밋 연결. create_order만 트랜잭션 하나로 묶는다. 파라미터 바인딩만 쓴다."""

    def __init__(self, database_url: str, schema: str | None = None) -> None:
        self._url = database_url
        self._schema = schema
        self._conn: psycopg.Connection | None = None

    def connect(self) -> None:
        self.close()
        conn = psycopg.connect(self._url, autocommit=True)
        if self._schema:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema)))
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except psycopg.Error:
                pass
            self._conn = None

    def _require(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            raise psycopg.OperationalError("연결이 없습니다")
        return self._conn

    def create_order(self, order: NewOrder, items: Sequence[NewOrderItem]) -> None:
        conn = self._require()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(ORDER_INSERT, astuple(order))
            cur.executemany(ITEM_INSERT, [astuple(item) for item in items])

    def add_payment(self, payment: NewPayment) -> None:
        self._require().execute(PAYMENT_INSERT, astuple(payment))

    def update_order_status(
        self, order_id: str, status: str, status_reason: str | None, updated_at: datetime
    ) -> None:
        self._require().execute(STATUS_UPDATE, (status, status_reason, updated_at, order_id))


class MemoryOrderSink:
    """테스트용. 호출을 순서대로 쌓는다."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.connects = 0

    def connect(self) -> None:
        self.connects += 1

    def close(self) -> None:
        pass

    def create_order(self, order: NewOrder, items: Sequence[NewOrderItem]) -> None:
        self.calls.append(("create_order", order, tuple(items)))

    def add_payment(self, payment: NewPayment) -> None:
        self.calls.append(("add_payment", payment))

    def update_order_status(
        self, order_id: str, status: str, status_reason: str | None, updated_at: datetime
    ) -> None:
        self.calls.append(("update_order_status", order_id, status, status_reason, updated_at))


def click_record(event: ClickEvent) -> dict[str, str]:
    """클릭 로그 한 건 (필드 6개). ingest_time은 파이프라인이 붙이므로 넣지 않는다."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "member_id": event.member_id,
        "article_id": event.article_id,
        "event_time": event.event_time.astimezone(KST).isoformat(),
        "session_id": event.session_id,
    }


class NullClickSink:
    def publish(self, event: ClickEvent) -> None:
        pass

    def close(self) -> None:
        pass


class JsonlClickSink:
    """한 줄에 이벤트 하나를 JSON으로 덧붙인다.

    줄마다 비우지 않고 기본 버퍼로 쓴다 (close에서 비운다). WSL의 /mnt 드라이브에서는
    줄마다 비우면 한 줄에 약 0.6ms가 걸려 피크 시간대의 클릭 속도를 따라가지 못한다.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file: TextIO | None = path.open("a", encoding="utf-8")

    def publish(self, event: ClickEvent) -> None:
        if self._file is None:
            raise RuntimeError("닫힌 클릭 파일입니다.")
        self._file.write(json.dumps(click_record(event), ensure_ascii=False) + "\n")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


class MemoryClickSink:
    """테스트용."""

    def __init__(self) -> None:
        self.events: list[ClickEvent] = []

    def publish(self, event: ClickEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass
