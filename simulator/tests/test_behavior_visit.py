import math
from collections import Counter
from datetime import datetime, timedelta
from itertools import pairwise

import pytest

from sim.behavior import params
from sim.behavior.model import CART_ADD, VIEW, VisitPlan
from sim.behavior.pool import MemberPool
from sim.behavior.visit import VisitContext, build_rankings, plan_visit, sample_view
from sim.common.rng import SimRandom, derive_seed
from sim.common.timezone import KST

START = datetime(2026, 10, 12, 9, 0, 0, tzinfo=KST)
SEED, SALT = 42, 1234
VISITS = 100_000


def _within(hits: int, n: int, p: float) -> bool:
    return abs(hits - n * p) <= 5 * math.sqrt(n * p * (1 - p))


@pytest.fixture(scope="module")
def ctx(member_ids, catalog) -> VisitContext:
    purchase, views = build_rankings(SEED, len(catalog))
    return VisitContext(MemberPool(SEED, member_ids), catalog, purchase, views)


_RNG = SimRandom(0)  # Faker를 매번 새로 만들지 않도록 하나를 다시 심어 쓴다 (실행기와 같다)


def _plan(ctx: VisitContext, k: int) -> VisitPlan:
    _RNG.reseed(derive_seed(SEED, "visit", SALT, k))
    return plan_visit(_RNG, k, START + timedelta(seconds=k), ctx)


@pytest.fixture(scope="module")
def plans(ctx) -> list[VisitPlan]:
    return [_plan(ctx, k) for k in range(VISITS)]


@pytest.fixture(scope="module")
def orders(plans):
    return [p.order for p in plans if p.order is not None]


def _has_cart(plan: VisitPlan) -> bool:
    return any(c.event_type == CART_ADD for c in plan.clicks)


def test_funnel(plans) -> None:
    carted = sum(1 for p in plans if _has_cart(p))
    ordered = sum(1 for p in plans if p.order is not None)
    direct = sum(1 for p in plans if p.order is not None and not _has_cart(p))
    p_order = params.DIRECT_ORDER_RATE + (1 - params.DIRECT_ORDER_RATE) * 0.15 * 0.28
    assert _within(carted, VISITS, (1 - params.DIRECT_ORDER_RATE) * params.CART_RATE)
    assert _within(ordered, VISITS, p_order)
    assert p_order == pytest.approx(0.0449, abs=1e-4)
    assert _within(direct, VISITS, params.DIRECT_ORDER_RATE)


def test_view_count(plans) -> None:
    counts = [sum(1 for c in p.clicks if c.event_type == VIEW) for p in plans]
    assert 4.8 <= sum(counts) / len(counts) <= 5.2
    assert min(counts) >= 1 and max(counts) <= 20


def test_line_and_quantity_distribution(orders) -> None:
    lines = Counter(len(o.items) for o in orders)
    n = len(orders)
    for p, low, high in params.LINE_COUNT_BUCKETS:
        assert _within(sum(lines[c] for c in range(low, high + 1)), n, p), (low, high)
    quantities = Counter(i.quantity for o in orders for i in o.items)
    total = sum(quantities.values())
    for q, p in params.QUANTITY_WEIGHTS:
        assert _within(quantities[q], total, p), q


def test_order_amounts_and_prices(orders, catalog) -> None:
    price = dict(zip(catalog.article_ids, catalog.prices, strict=True))
    for o in orders:
        articles = [i.article_id for i in o.items]
        assert len(articles) == len(set(articles))  # 한 주문 안 중복 없음
        assert o.order.total_amount == sum(i.quantity * i.unit_price for i in o.items)
        assert all(i.unit_price == price[i.article_id] for i in o.items)
        assert all(i.order_id == o.order.order_id for i in o.items)
        assert o.order.status == "PLACED" and o.order.updated_at == o.order.ordered_at


def test_method_distribution(orders) -> None:
    methods = Counter(o.method for o in orders)
    for method, p in params.METHOD_WEIGHTS:
        assert _within(methods[method], len(orders), p)


def test_pre_payment_cancel_rate(orders) -> None:
    cancelled = sum(1 for o in orders if o.cancel_at is not None)
    assert _within(cancelled, len(orders), params.PRE_PAYMENT_CANCEL_RATE)


def test_consistency_rules(plans) -> None:
    sessions = set()
    for p in plans:
        assert p.session_id not in sessions
        sessions.add(p.session_id)
        assert all(c.member_id == p.member_id and c.session_id == p.session_id for c in p.clicks)
        times = [c.event_time for c in p.clicks]
        assert times == sorted(times)
        assert p.clicks[0].event_type == VIEW and p.clicks[0].event_time == p.arrived_at
        for i, c in enumerate(p.clicks):
            if c.event_type == CART_ADD:  # 같은 세션에서 먼저 본 상품만 담는다
                assert any(
                    v.event_type == VIEW and v.article_id == c.article_id for v in p.clicks[:i]
                )
        if p.order is not None:
            o = p.order.order
            assert o.session_id == p.session_id and o.member_id == p.member_id
            assert o.ordered_at > p.clicks[-1].event_time  # 클릭 로그가 먼저 있다
            ordered = {i.article_id for i in p.order.items}
            assert ordered <= {c.article_id for c in p.clicks if c.event_type == VIEW}
            if _has_cart(p):
                carted = {c.article_id for c in p.clicks if c.event_type == CART_ADD}
                assert carted == ordered  # 담은 것 전부 주문


def test_times_within_ranges(plans) -> None:
    for p in plans[:20_000]:
        views = [c for c in p.clicks if c.event_type == VIEW]
        for a, b in pairwise(views):
            assert 10 <= (b.event_time - a.event_time).total_seconds() <= 60
        for c in p.clicks:
            if c.event_type == CART_ADD:
                gaps = [
                    (c.event_time - v.event_time).total_seconds()
                    for v in views
                    if v.article_id == c.article_id
                ]
                assert any(5 <= g <= 30 for g in gaps)
        if p.order is not None:
            o = p.order
            assert 20 <= (o.order.ordered_at - p.clicks[-1].event_time).total_seconds() <= 120
            assert 3 <= (o.first_attempt_at - o.order.ordered_at).total_seconds() <= 30
            if o.cancel_at is not None:
                assert 60 <= (o.cancel_at - o.order.ordered_at).total_seconds() <= 300


def test_view_ranking_differs_from_purchase(ctx) -> None:
    rng = SimRandom(5)
    top = set(ctx.purchase.order[: len(ctx.catalog) // 100])  # 구매 상위 1%
    draws = 100_000
    hits = sum(1 for _ in range(draws) if sample_view(rng, ctx) in top)
    assert 0.05 <= hits / draws <= 0.08


def test_visit_plan_is_independent_of_order(ctx, plans) -> None:
    for k in (0, 37, 4_242, VISITS - 1):
        assert _plan(ctx, k) == plans[k]


def test_different_salt_gives_different_ids(ctx, plans) -> None:
    rng = SimRandom(derive_seed(SEED, "visit", SALT + 1, 0))
    other = plan_visit(rng, 0, START, ctx)
    assert other.session_id != plans[0].session_id


def test_naive_time_is_rejected(ctx) -> None:
    with pytest.raises(ValueError):
        plan_visit(SimRandom(1), 0, datetime(2026, 10, 12, 9, 0, 0), ctx)
