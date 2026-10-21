"""업무 API로 주문·결제·상태·클릭을 보내고 회원·상품 목록을 읽는다. DB 계정이 필요 없다.

- ApiOrderSink: OrderSink 구현. 같은 ID 재전송은 API가 200으로 받는다(재시도 안전)
- ApiClickSink: ClickSink 구현. 1초 또는 500건마다 묶어 보낸다. 실패한 묶음은 버리고 센다
- ApiMemberSource: 처음엔 활성 회원 전체, 그다음부터는 변경분만 받아 목록을 유지한다
- ApiCatalogSource: 상품 가격 전체(시작 때 한 번)
"""

import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import datetime

from sim.behavior.model import Catalog, ClickEvent, NewOrder, NewOrderItem, NewPayment
from sim.behavior.sink import click_record
from sim.common.api import ApiClient, StoreRejected, StoreUnavailable

CLICK_BATCH_MAX = 500
CLICK_FLUSH_SECONDS = 1.0
MEMBER_REFRESH_SECONDS = 5.0  # 변경분을 묻는 주기 (실제 시간)


def _stderr_warn(message: str) -> None:
    print(f"경고: {message}", file=sys.stderr)


class ApiOrderSink:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def connect(self) -> None:
        self._client.health()

    def close(self) -> None:
        pass

    def create_order(self, order: NewOrder, items: Sequence[NewOrderItem]) -> None:
        body = {
            "order_id": order.order_id,
            "member_id": order.member_id,
            "session_id": order.session_id,
            "status": order.status,
            "total_amount": order.total_amount,
            "ordered_at": order.ordered_at,
            "items": [
                {
                    "order_item_id": i.order_item_id,
                    "article_id": i.article_id,
                    "quantity": i.quantity,
                    "unit_price": i.unit_price,
                }
                for i in items
            ],
        }
        self._client.request("POST", "/v1/orders", body)

    def add_payment(self, payment: NewPayment) -> None:
        body = {f.name: getattr(payment, f.name) for f in fields(payment) if f.name != "order_id"}
        self._client.request("POST", f"/v1/orders/{payment.order_id}/payments", body)

    def update_order_status(
        self, order_id: str, status: str, status_reason: str | None, updated_at: datetime
    ) -> None:
        body = {"status": status, "status_reason": status_reason, "updated_at": updated_at}
        self._client.request("PATCH", f"/v1/orders/{order_id}", body)


@dataclass
class ClickStats:
    sent: int = 0
    failed: int = 0


class ApiClickSink:
    """publish()는 막히지 않는다. 묶음 전송은 뒤에서 1초마다, 또는 500건이 차면 바로 한다."""

    def __init__(
        self,
        client: ApiClient,
        warn: Callable[[str], None] = _stderr_warn,
        flush_seconds: float = CLICK_FLUSH_SECONDS,
        start_timer: bool = True,
    ) -> None:
        self._client = client
        self._warn = warn
        self._buffer: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._warned = False
        self.stats = ClickStats()
        self._stop = threading.Event()
        self._flush_seconds = flush_seconds
        self._timer: threading.Thread | None = None
        if start_timer:
            self._timer = threading.Thread(target=self._loop, name="click-flush", daemon=True)
            self._timer.start()

    def publish(self, event: ClickEvent) -> None:
        with self._lock:
            self._buffer.append(click_record(event))
            full = len(self._buffer) >= CLICK_BATCH_MAX
        if full:
            self.flush()

    def _loop(self) -> None:
        while not self._stop.wait(self._flush_seconds):
            self.flush()

    def flush(self) -> None:
        with self._send_lock:
            with self._lock:
                batch, self._buffer = self._buffer[:CLICK_BATCH_MAX], self._buffer[CLICK_BATCH_MAX:]
            if not batch:
                return
            try:
                body = self._client.request("POST", "/v1/events/clicks", {"events": batch}).body
                sent, failed = int(body.get("accepted", 0)), int(body.get("failed", 0))
            except (StoreUnavailable, StoreRejected) as error:
                sent, failed = 0, len(batch)
                if not self._warned:
                    self._warned = True
                    self._warn(f"클릭 전송 실패, 버리고 셉니다: {error}")
            self.stats.sent += sent
            self.stats.failed += failed

    def close(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.join(timeout=5)
        deadline = time.monotonic() + 30
        while self._buffer and time.monotonic() < deadline:
            self.flush()


class ApiMemberSource:
    """활성 회원 목록을 API로 유지한다. refresh_seconds는 실행기가 읽는 갱신 주기다."""

    refresh_seconds = MEMBER_REFRESH_SECONDS

    def __init__(self, client: ApiClient) -> None:
        self._client = client
        self._ids: set[str] = set()
        self._changes_cursor: str | None = None

    def read_active_members(self) -> list[str]:
        """처음 부르면 전체, 그다음부터는 변경분만 받아 합친 목록. 실패하면 StoreUnavailable."""
        if self._changes_cursor is None:
            self._load_all()
        else:
            self._apply_changes()
        return sorted(self._ids)

    def _load_all(self) -> None:
        ids: set[str] = set()
        cursor: str | None = None
        changes: str | None = None
        while True:
            body = self._client.get("/v1/members/active", {"cursor": cursor} if cursor else None)
            ids.update(body["items"])
            changes = changes or body.get("changes_cursor")
            cursor = body.get("next_cursor")
            if not cursor:
                break
        self._ids = ids
        self._changes_cursor = changes

    def _apply_changes(self) -> None:
        while True:
            body = self._client.get("/v1/members/changes", {"after": self._changes_cursor})
            self._ids.update(body.get("added", []))
            self._ids.difference_update(body.get("removed", []))
            self._changes_cursor = body["next_cursor"]
            if not body.get("has_more"):
                break

    def discard(self, member_id: str) -> None:
        """주문 API가 MEMBER_NOT_ACTIVE로 거절한 회원을 뺀다."""
        self._ids.discard(member_id)


class ApiCatalogSource:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def read_catalog(self) -> Catalog:
        articles: list[str] = []
        prices: list[int] = []
        cursor: str | None = None
        while True:
            body = self._client.get("/v1/catalog", {"cursor": cursor} if cursor else None)
            for item in body["items"]:
                articles.append(str(item["article_id"]))
                prices.append(int(item["price"]))
            cursor = body.get("next_cursor")
            if not cursor:
                break
        return Catalog(tuple(articles), tuple(prices))


__all__ = ["ApiCatalogSource", "ApiClickSink", "ApiMemberSource", "ApiOrderSink", "ClickStats"]
