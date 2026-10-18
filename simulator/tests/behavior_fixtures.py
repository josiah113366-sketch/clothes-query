"""행동 테스트용 합성 데이터와 가짜 원천 (DB 없이)."""

import uuid

from sim.behavior.model import Catalog


def make_member_ids(count: int) -> list[str]:
    return sorted(str(uuid.UUID(int=i + 1)) for i in range(count))


def make_catalog(count: int) -> Catalog:
    article_ids = tuple(f"{i:010d}" for i in range(100_000_001, 100_000_001 + count))
    prices = tuple(5_900 + 500 * (i % 60) for i in range(count))
    return Catalog(article_ids, prices)


class StaticMembers:
    def __init__(self, member_ids: list[str]) -> None:
        self.member_ids = member_ids
        self.reads = 0
        self.fail = False

    def read_active_members(self) -> list[str]:
        self.reads += 1
        if self.fail:
            raise OSError("읽기 실패")
        return list(self.member_ids)


class StaticCatalog:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def read_catalog(self) -> Catalog:
        return self.catalog


# --- 실행기 테스트 도구 ---

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sim.common.control import ControlState


class Script:
    """실제 경과 시간(초)에 따라 제어 상태를 바꾸는 가짜 제어 신호."""

    def __init__(self, clock, steps: list[tuple[float, ControlState]]) -> None:
        self.clock, self.steps = clock, steps

    def read(self) -> ControlState | None:
        t = self.clock.real_elapsed()
        current = None
        for at, state in self.steps:
            if t >= at:
                current = state
        return current


@dataclass
class OrderState:
    order: object
    items: tuple
    payments: list = field(default_factory=list)
    updates: list = field(default_factory=list)  # (status, reason, at)

    @property
    def status(self) -> str:
        return self.updates[-1][0] if self.updates else "PLACED"


def replay(calls: list[tuple]) -> dict[str, OrderState]:
    """MemoryOrderSink의 호출 기록을 주문별 상태로 모은다."""
    orders: dict[str, OrderState] = {}
    for call in calls:
        if call[0] == "create_order":
            orders[call[1].order_id] = OrderState(call[1], call[2])
        elif call[0] == "add_payment":
            orders[call[1].order_id].payments.append(call[1])
        else:
            _, order_id, status, reason, at = call
            orders[order_id].updates.append((status, reason, at))
    return orders


def consistency_problems(orders: dict[str, OrderState], clicks: list) -> list[str]:
    """지시서의 정합성 규칙. 어긋난 곳을 모두 돌려준다 (없으면 빈 목록)."""
    problems: list[str] = []
    by_session: dict[str, list] = defaultdict(list)
    for c in clicks:
        by_session[c.session_id].append(c)
    for session, events in by_session.items():
        viewed: set[str] = set()
        for c in sorted(events, key=lambda e: e.event_time):
            if c.event_type == "view":
                viewed.add(c.article_id)
            elif c.article_id not in viewed:
                problems.append(f"cart_add without view: {session}")
    for order_id, s in orders.items():
        o = s.order
        if o.session_id not in by_session:
            problems.append(f"orphan order: {order_id}")
        if o.total_amount != sum(i.quantity * i.unit_price for i in s.items):
            problems.append(f"total mismatch: {order_id}")
        attempts = [p.attempt_no for p in s.payments]
        if attempts != list(range(1, len(attempts) + 1)) or len(attempts) > 3:
            problems.append(f"attempt numbers: {order_id}")
        successes = sum(1 for p in s.payments if p.status == "SUCCESS")
        if successes > 1:
            problems.append(f"two successes: {order_id}")
        statuses = [u[0] for u in s.updates]
        if "PAID" in statuses and successes != 1:
            problems.append(f"paid without one success: {order_id}")
        if s.status == "PAYMENT_FAILED" and (successes or not s.payments):
            problems.append(f"payment_failed mismatch: {order_id}")
        if statuses[:1] == ["CANCELLED"] and s.payments:
            problems.append(f"pre-payment cancel has payments: {order_id}")
        for p in s.payments:
            if p.completed_at < p.requested_at or p.amount != o.total_amount:
                problems.append(f"payment fields: {order_id}")
        times = [o.ordered_at] + [u[2] for u in s.updates]
        if times != sorted(times):
            problems.append(f"updated_at not increasing: {order_id}")
        for status, reason, _ in s.updates:
            expected = {"CANCELLED": "USER_REQUEST", "REFUNDED": "RETURN"}.get(status)
            if reason != expected:
                problems.append(f"status_reason: {order_id}")
        terminal = {"CANCELLED", "PAYMENT_FAILED", "REFUNDED"}
        for status in statuses[:-1]:
            if status in terminal:
                problems.append(f"change after terminal {status}: {order_id}")
                break
    return problems


def first_monday() -> datetime:
    from sim.common.timezone import KST

    return datetime(2026, 10, 12, 0, 0, 0, tzinfo=KST)
