"""방문 한 건의 계획. 순수 함수다 (DB, 네트워크, 현재 시각을 부르지 않는다).

방문 k의 난수는 실행기가 derive_seed(seed, "visit", run_salt, k)로 다시 심어서 넘긴다.
그래서 k번째 방문의 계획은 앞선 방문과 무관하다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate

from sim.behavior import params
from sim.behavior.model import (
    CART_ADD,
    PLACED,
    VIEW,
    Catalog,
    ClickEvent,
    NewOrder,
    NewOrderItem,
    OrderPlan,
    VisitPlan,
)
from sim.behavior.pool import MemberPool
from sim.behavior.ranking import ProductRanking
from sim.common.rng import SimRandom, derive_seed

_LINE_BUCKETS = [(lo, hi) for _, lo, hi in params.LINE_COUNT_BUCKETS]
_LINE_CUM = list(accumulate(p for p, _, _ in params.LINE_COUNT_BUCKETS))
_QUANTITIES = [q for q, _ in params.QUANTITY_WEIGHTS]
_QUANTITY_CUM = list(accumulate(w for _, w in params.QUANTITY_WEIGHTS))
_METHODS = [m for m, _ in params.METHOD_WEIGHTS]
_METHOD_CUM = list(accumulate(w for _, w in params.METHOD_WEIGHTS))


@dataclass(frozen=True)
class VisitContext:
    """모든 방문이 같이 쓰는 입력."""

    pool: MemberPool
    catalog: Catalog
    purchase: ProductRanking
    views: ProductRanking


def build_rankings(seed: int, size: int) -> tuple[ProductRanking, ProductRanking]:
    """구매 순위와 조회 순위. 서로 다른 줄기의 시드로 섞는다."""
    purchase = ProductRanking(size, derive_seed(seed, "purchase-ranking"), params.PURCHASE_CURVE)
    views = ProductRanking(size, derive_seed(seed, "view-ranking"), params.PURCHASE_CURVE)
    return purchase, views


def after(rng: SimRandom, at: datetime, bounds: tuple[float, float]) -> datetime:
    """at에서 균등 분포 [a, b]초 뒤."""
    return at + timedelta(seconds=rng.random.uniform(*bounds))


def draw_view_count(rng: SimRandom) -> int:
    n = 1 + round(rng.random.expovariate(1 / params.VIEW_EXTRA_MEAN))
    return max(params.VIEW_COUNT_MIN, min(n, params.VIEW_COUNT_MAX))


def draw_line_count(rng: SimRandom) -> int:
    low, high = rng.weighted_choice(_LINE_BUCKETS, _LINE_CUM)
    return rng.randint(low, high)


def draw_quantity(rng: SimRandom) -> int:
    return rng.weighted_choice(_QUANTITIES, _QUANTITY_CUM)


def draw_method(rng: SimRandom) -> str:
    return rng.weighted_choice(_METHODS, _METHOD_CUM)


def sample_view(rng: SimRandom, ctx: VisitContext) -> int:
    """조회 상품: 70%는 조회 순위, 30%는 구매 순위에서."""
    ranking = ctx.views if rng.chance(params.VIEW_FROM_VIEW_RANKING) else ctx.purchase
    return ranking.sample(rng)


def plan_visit(rng: SimRandom, visit_no: int, arrived_at: datetime, ctx: VisitContext) -> VisitPlan:
    if arrived_at.tzinfo is None:
        raise ValueError("arrived_at은 시간대 정보가 있는 값이어야 합니다.")
    member_id = ctx.pool.sample(rng)
    session_id = rng.uuid4()

    # 퍼널: 바로 주문 / 담기 → (주문 | 이탈) / 이탈
    direct = rng.chance(params.DIRECT_ORDER_RATE)
    carted = not direct and rng.chance(params.CART_RATE)
    ordered = direct or (carted and rng.chance(params.CART_TO_ORDER_RATE))
    if ordered:
        pick_count = draw_line_count(rng)
    elif carted:
        pick_count = rng.randint(*params.CART_ONLY_ITEMS)
    else:
        pick_count = 0
    pick_count = min(pick_count, len(ctx.catalog))
    picks = ctx.purchase.sample_distinct(rng, pick_count)

    # 조회 목록: 담을 상품을 무작위 위치에 끼우고 나머지는 조회 분포에서
    view_count = max(draw_view_count(rng), pick_count)
    pick_positions = rng.random.sample(range(view_count), pick_count)
    viewed: list[int | None] = [None] * view_count
    for position, index in zip(pick_positions, picks, strict=True):
        viewed[position] = index
    view_items = [index if index is not None else sample_view(rng, ctx) for index in viewed]

    # 시각: 첫 조회 = 도착, 이후 간격 10~60초. 담기는 그 상품 조회 뒤 5~30초
    times = [arrived_at]
    for _ in range(view_count - 1):
        times.append(after(rng, times[-1], params.VIEW_GAP_SECONDS))
    article = ctx.catalog.article_ids
    events: list[ClickEvent] = [
        ClickEvent(rng.uuid4(), VIEW, member_id, article[i], t, session_id)
        for i, t in zip(view_items, times, strict=True)
    ]
    if carted:
        for position, index in zip(pick_positions, picks, strict=True):
            at = after(rng, times[position], params.CART_AFTER_VIEW_SECONDS)
            events.append(
                ClickEvent(rng.uuid4(), CART_ADD, member_id, article[index], at, session_id)
            )
    clicks = tuple(sorted(events, key=lambda e: e.event_time))  # 같은 시각이면 만든 순서

    order = None
    if ordered:
        last_event = clicks[-1].event_time
        order = _plan_order(rng, member_id, session_id, picks, last_event, ctx.catalog)
    return VisitPlan(visit_no, session_id, member_id, arrived_at, clicks, order)


def _plan_order(
    rng: SimRandom,
    member_id: str,
    session_id: str,
    picks: list[int],
    last_event: datetime,
    catalog: Catalog,
) -> OrderPlan:
    order_id = rng.uuid4()
    items = tuple(
        NewOrderItem(
            rng.uuid4(), order_id, catalog.article_ids[i], draw_quantity(rng), catalog.prices[i]
        )
        for i in picks
    )
    total = sum(item.quantity * item.unit_price for item in items)
    method = draw_method(rng)
    ordered_at = after(rng, last_event, params.ORDER_AFTER_LAST_EVENT_SECONDS)
    first_attempt_at = after(rng, ordered_at, params.FIRST_ATTEMPT_DELAY_SECONDS)
    cancel_at = None
    if rng.chance(params.PRE_PAYMENT_CANCEL_RATE):
        cancel_at = after(rng, ordered_at, params.PRE_PAYMENT_CANCEL_SECONDS)
    order = NewOrder(order_id, member_id, session_id, PLACED, None, total, ordered_at, ordered_at)
    return OrderPlan(order, items, method, first_attempt_at, cancel_at)
