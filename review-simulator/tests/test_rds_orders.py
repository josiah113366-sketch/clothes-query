"""RDS orders 테이블 기반 리뷰(--source rds, 2026-10-21) 테스트. 실제 DB 대신 가짜 연결을 쓴다.

확인하는 것
- SQL 결과 한 줄 → Order 변환(상품 정보·연령대·주문 항목 키)
- RdsOrderSource 가 읽기 전용으로 열고, 상태·결제 시각 범위를 파라미터로 넘기는지
- run(source="rds") 가 주문 항목마다 리뷰 하나를 만들고, RDS 값(order_id·member_id·article_id·연령대)을 그대로 쓰는지
- 프롬프트에 RDS 상품 정보(product_info)와 연령대가 들어가는지
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from rsim.common.config import load_settings
from rsim.common.rng import make_rng
from rsim.review.generator import build_user_prompt
from rsim.review.orders import (
    RDS_REVIEW_STATUSES,
    RdsOrderSource,
    ReviewTiming,
    due_orders,
    order_from_row,
)
from rsim.review.run import make_order_source
from rsim.review.run import run as run_reviews

PAID0 = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)


def _row(i: int, order: int | None = None, paid_at: datetime = PAID0, age_band="20s") -> dict:
    """RDS_ORDERS_SQL 결과 모양의 가짜 한 줄. order 를 주면 같은 주문의 다른 항목이 된다."""
    o = order if order is not None else i
    return {
        "order_id": f"00000000-0000-0000-0000-{o:012d}",
        "member_id": f"11111111-0000-0000-0000-{o:012d}",
        "order_item_id": f"22222222-0000-0000-0000-{i:012d}",
        "article_id": f"0{108775015 + i % 3}",
        "paid_at": paid_at + timedelta(minutes=i),
        "age_band": age_band,
        "prod_name": "Strap top",
        "colour_group_name": "Black",
        "graphical_appearance_name": "Solid",
        "product_type_name": "Vest top",
    }


class FakeCursor:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.log["sql"], self.log["params"] = sql, params

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log
        self.read_only = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.log["read_only"] = self.read_only
        return False

    def cursor(self):
        return FakeCursor(self.rows, self.log)


def _source(rows, log=None, since=PAID0 - timedelta(days=30), until=PAID0 + timedelta(days=30)):
    log = {} if log is None else log
    return RdsOrderSource(
        "postgresql://test", since, until, connect=lambda url: FakeConn(rows, log)
    )


def test_order_from_row_maps_product_and_age() -> None:
    o = order_from_row(_row(1))
    assert o.key == o.order_item_id  # 주문 항목 하나 = 리뷰 하나
    assert o.product_id == o.product.product_id == "0108775016"
    assert o.product.product_name == "Strap top" and o.product.category is None
    assert o.product.info == {"product_type": "Vest top", "color": "Black", "pattern": "Solid"}
    assert o.age_group == "20대"
    # 같은 상품이면 기본 만족도 편차도 항상 같다
    assert o.product.quality_bias == order_from_row(_row(4)).product.quality_bias
    assert order_from_row(_row(1, age_band=None)).age_group is None
    with pytest.raises(SystemExit):
        order_from_row({**_row(1), "paid_at": datetime(2026, 10, 14)})  # 시간대 없음


def test_rds_source_reads_only_and_passes_filters() -> None:
    log: dict = {}
    orders = _source([_row(1), _row(2)], log).load()
    assert len(orders) == 2
    assert log["read_only"] is True
    assert log["params"]["statuses"] == list(RDS_REVIEW_STATUSES)
    assert "CANCELLED" not in RDS_REVIEW_STATUSES and "REFUNDED" not in RDS_REVIEW_STATUSES
    # 개인정보 컬럼은 쿼리에 없다
    for col in ("name", "email", "phone", "birth_date"):
        assert f"m.{col}" not in log["sql"]
    with pytest.raises(SystemExit):
        RdsOrderSource("", PAID0, PAID0).load()


def test_make_order_source_window_covers_review_delay(workdir, monkeypatch) -> None:
    monkeypatch.setenv(
        "ORDERS_DATABASE_URL", "postgresql://test"
    )  # 연결은 하지 않는다(load 를 안 부름)
    settings = load_settings()
    timing = ReviewTiming(min_days=1, max_days=7)
    start = datetime(2026, 10, 21, tzinfo=UTC)
    src = make_order_source("rds", settings, Path("x"), timing, start, start + timedelta(days=1))
    # 리뷰 날짜 D 에 걸릴 수 있는 결제(D-7 ~ D) 가 모두 범위 안
    assert src.since <= start - timedelta(days=7)
    assert src.until >= start


def test_items_of_same_order_get_separate_reviews() -> None:
    # 한 주문에 상품 3개 → 리뷰 키가 3개 (같은 주문이어도 텀이 항목마다 다를 수 있다)
    orders = [order_from_row(_row(i, order=7)) for i in range(3)]
    assert len({o.key for o in orders}) == 3 and len({o.order_id for o in orders}) == 1
    timing = ReviewTiming()
    seen = []
    for d in range(10):
        start = datetime(2026, 10, 14, tzinfo=UTC) + timedelta(days=d)
        seen += [o.key for o, _ in due_orders(orders, timing, start, start + timedelta(days=1))]
    assert sorted(seen) == sorted(o.key for o in orders)


def _lake_rows(workdir: Path, table: str) -> list[dict]:
    rows = []
    for f in sorted((workdir / ".local/lake" / table).rglob("part-00000.jsonl")):
        rows += [json.loads(x) for x in f.read_text("utf-8").splitlines() if x.strip()]
    return rows


def test_run_from_rds_writes_reviews_with_rds_values(workdir) -> None:
    rows = [_row(i, order=i // 2) for i in range(40)]  # 주문 20건, 주문마다 항목 2개
    by_item = {r["order_item_id"]: r for r in rows}
    total = 0
    for d in range(14, 23):
        total += run_reviews(
            llm="fake",
            sink_kind="lake",
            source="rds",
            day=date(2026, 10, d),
            order_source=_source(rows),
        )
    reviews = _lake_rows(workdir, "reviews")
    # 모든 항목에 리뷰 하나씩 (REVIEW_RATE 기본 1.0), 결제 후 1~7일 안
    assert total == len(reviews) == len(rows)
    for r in reviews:
        assert r["source"] == "simulator" and r["age_group"] == "20대"
        assert (
            r["category"] is None and r["option_color"] == "블랙"
        )  # 상품 색상(영문)을 한국어 옵션으로
        matches = [x for x in rows if x["order_id"] == r["order_id"]]
        assert r["member_id"] == matches[0]["member_id"]
        assert r["product_id"] in {x["article_id"] for x in matches}
        delay = datetime.fromisoformat(r["created_at"]) - datetime.fromisoformat(r["purchased_at"])
        assert timedelta(days=1) <= delay <= timedelta(days=7)
    assert len({r["review_id"] for r in reviews}) == len(rows)
    assert len(by_item) == len(rows)


def test_prompt_uses_rds_product_info_and_age(workdir) -> None:
    from rsim.review.catalog import Catalog
    from rsim.review.scenario import ScenarioEngine, SimClock

    names = {"여성의류": ["니트"], "남성의류": ["셔츠"], "패션슈즈": ["운동화"], "잡화": ["가방"]}
    rng = make_rng(0)
    catalog = Catalog.build(Path("없는파일.csv"), names, rng)
    engine = ScenarioEngine(catalog, [], SimClock(None, 20.0, rng), rng, id_rng=make_rng(1))
    o = order_from_row(_row(1, age_band="40s"))
    spec = engine.spec_for_order(o.product, PAID0, o.member_id, o.age_group)
    assert spec.age_group == "40대" and spec.member_id == o.member_id
    prompt = build_user_prompt([spec], [])
    assert "Strap top" in prompt and "Vest top" in prompt and "Black" in prompt
    assert "40대" in prompt
