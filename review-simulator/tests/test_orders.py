"""주문 기반 리뷰 발생(orders.py)과 rsim run --source orders 흐름 테스트. Bedrock·DB 는 부르지 않는다."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from rsim.cli import app
from rsim.common.rng import make_rng
from rsim.review.catalog import Catalog
from rsim.review.orders import Order, ReviewTiming, due_orders, fake_orders

runner = CliRunner()
T0 = datetime.fromisoformat("2026-10-01T00:00:00+09:00")


def _order(i: int, paid_at: datetime = T0) -> Order:
    return Order(
        order_id=f"O-{i:04d}", member_id=f"C-{i:04d}", product_id="W-0001", paid_at=paid_at
    )


def test_due_at_is_fixed_per_order_and_within_range() -> None:
    timing = ReviewTiming()
    for i in range(300):
        o = _order(i)
        due = timing.due_at(o)
        assert due == timing.due_at(o)  # 같은 주문이면 항상 같은 시각
        assert o.paid_at + timedelta(days=1) <= due <= o.paid_at + timedelta(days=14)


def test_review_rate() -> None:
    assert all(ReviewTiming(rate=0.0).due_at(_order(i)) is None for i in range(100))
    picked = sum(ReviewTiming(rate=0.3).due_at(_order(i)) is not None for i in range(2000))
    assert 450 < picked < 750  # 약 30%


def test_due_orders_skips_reviewed_and_future() -> None:
    timing = ReviewTiming()
    orders = [_order(i) for i in range(50)]
    now = T0 + timedelta(days=7)
    due = due_orders(orders, timing, now, reviewed={"O-0001", "O-0002"})
    ids = {o.order_id for o, _ in due}
    assert ids.isdisjoint({"O-0001", "O-0002"})
    assert all(at <= now for _, at in due)
    assert [at for _, at in due] == sorted(at for _, at in due)
    # 14일이 지나면(이미 리뷰 있는 2건 빼고) 전부 차례가 된다
    assert len(due_orders(orders, timing, T0 + timedelta(days=15), {"O-0001", "O-0002"})) == 48


def test_fake_orders_reproducible() -> None:
    names = {"여성의류": ["니트"], "남성의류": ["셔츠"], "패션슈즈": ["운동화"], "잡화": ["가방"]}
    catalog = Catalog.build(Path("없는파일.csv"), names, make_rng(0))
    a = fake_orders(catalog, make_rng(1), T0, days=3, per_day=200)
    b = fake_orders(catalog, make_rng(1), T0, days=3, per_day=200)
    assert a == b
    assert 450 < len(a) < 750  # 하루 200건 x 3일 근처
    assert all(T0 <= o.paid_at < T0 + timedelta(days=3) and o.paid_at.tzinfo for o in a)
    assert {o.product_id for o in a} <= set(catalog.by_id)


def _reviews(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def test_run_from_orders_twice_does_not_duplicate(workdir) -> None:
    res = runner.invoke(
        app,
        ["orders-fake", "--start", "2026-10-01T00:00:00+09:00", "--days", "3", "--per-day", "20"],
    )
    assert res.exit_code == 0, res.output
    orders = {o["order_id"]: o for o in _reviews(workdir / ".local/orders.jsonl")}

    args = ["run", "--source", "orders", "--llm", "fake", "--sink", "jsonl", "--now"]
    res = runner.invoke(app, [*args, "2026-10-08T00:00:00+09:00"])
    assert res.exit_code == 0, res.output
    out = workdir / ".local/out/reviews.jsonl"
    first = _reviews(out)
    assert first, "1주일 뒤에는 차례가 된 주문이 있어야 한다"
    for r in first:
        o = orders[r["order_id"]]
        assert r["member_id"] == o["member_id"] and r["product_id"] == o["product_id"]
        created = datetime.fromisoformat(r["created_at"])
        paid = datetime.fromisoformat(o["paid_at"])
        assert (
            paid + timedelta(days=1)
            <= created
            <= datetime.fromisoformat("2026-10-08T00:00:00+09:00")
        )

    # 같은 시각으로 다시 돌리면 새로 만들 주문이 없다
    runner.invoke(app, [*args, "2026-10-08T00:00:00+09:00"])
    assert len(_reviews(out)) == len(first)

    # 3주 뒤에는 모든 주문에 리뷰가 하나씩만 있다
    runner.invoke(app, [*args, "2026-10-22T00:00:00+09:00"])
    ids = [r["order_id"] for r in _reviews(out)]
    assert len(ids) == len(set(ids)) == len(orders)
    truth = _reviews(workdir / ".local/out/reviews_truth.jsonl")
    assert [t["order_id"] for t in truth] == ids
