"""주문 기반 리뷰 발생(orders.py)과 rsim run --source orders 흐름 테스트. Bedrock·DB 는 부르지 않는다."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
        assert o.paid_at + timedelta(days=1) <= due <= o.paid_at + timedelta(days=7)


def test_review_rate() -> None:
    assert all(ReviewTiming(rate=0.0).due_at(_order(i)) is None for i in range(100))
    picked = sum(ReviewTiming(rate=0.3).due_at(_order(i)) is not None for i in range(2000))
    assert 450 < picked < 750  # 약 30%


def test_due_orders_window() -> None:
    timing = ReviewTiming()
    orders = [_order(i) for i in range(200)]
    day = T0 + timedelta(days=5)
    due = due_orders(orders, timing, day, day + timedelta(days=1))
    assert due and all(day <= at < day + timedelta(days=1) for _, at in due)
    assert [at for _, at in due] == sorted(at for _, at in due)
    # 날짜를 하루씩 이어 붙이면 모든 주문이 정확히 한 번씩 나온다
    seen = []
    for d in range(16):
        start = T0 + timedelta(days=d)
        seen += [
            o.order_id for o, _ in due_orders(orders, timing, start, start + timedelta(days=1))
        ]
    assert sorted(seen) == sorted(o.order_id for o in orders)


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


def _lake(workdir: Path, table: str) -> dict[str, list[dict]]:
    root = workdir / ".local/lake" / table
    # year=YYYY/month=MM/day=DD 파티션을 "YYYY-MM-DD" 키로 모은다
    parts = {}
    for d in sorted(root.glob("year=*/month=*/day=*")):
        day = "-".join(p.split("=")[1] for p in d.relative_to(root).parts)
        parts[day] = _reviews(d / "part-00000.jsonl")
    return parts


def test_run_from_orders_by_date_to_lake(workdir) -> None:
    res = runner.invoke(
        app,
        ["orders-fake", "--start", "2026-10-01T00:00:00+09:00", "--days", "3", "--per-day", "20"],
    )
    assert res.exit_code == 0, res.output
    orders = {o["order_id"]: o for o in _reviews(workdir / ".local/orders.jsonl")}

    args = ["run", "--source", "orders", "--llm", "fake", "--sink", "lake", "--date"]
    res = runner.invoke(app, [*args, "2026-10-08"])
    assert res.exit_code == 0, res.output
    first = _lake(workdir, "reviews")["2026-10-08"]
    assert first
    for r in first:
        o = orders[r["order_id"]]
        assert r["member_id"] == o["member_id"] and r["product_id"] == o["product_id"]
        assert r["purchased_at"] == o["paid_at"]
        assert r["schema_version"] == "review.v2" and r["option_size"] and r["option_color"]
        assert isinstance(r["has_photo"], bool) and r["emitted_at"]
        created = datetime.fromisoformat(r["created_at"])
        assert created.astimezone(UTC).date().isoformat() == "2026-10-08"  # dt = UTC 날짜

    # 같은 날짜를 다시 돌리면 파티션을 덮어써서 같은 주문·같은 ID·같은 옵션이 남는다
    runner.invoke(app, [*args, "2026-10-08"])
    again = _lake(workdir, "reviews")["2026-10-08"]

    def strip(rows):
        keys = ("review_id", "order_id", "option_size", "option_color", "has_photo", "created_at")
        return [tuple(r[k] for k in keys) for r in rows]

    assert strip(again) == strip(first)

    # 모든 날짜를 돌리면 주문마다 리뷰가 정확히 하나
    for d in range(1, 20):
        runner.invoke(app, [*args, f"2026-10-{d:02d}"])
    parts = _lake(workdir, "reviews")
    ids = [r["order_id"] for rows in parts.values() for r in rows]
    assert len(ids) == len(set(ids)) == len(orders)
    truth = _lake(workdir, "reviews_truth")
    assert {k: [t["review_id"] for t in v] for k, v in truth.items()} == {
        k: [r["review_id"] for r in v] for k, v in parts.items()
    }


def test_lake_sink_writes_s3_with_fake_bucket(monkeypatch) -> None:
    # moto 의 가짜 S3 로 확인한다(실제 AWS 호출 없음). 같은 날짜를 두 번 써도 객체 하나로 덮어써진다
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    from rsim.review.sinks import LakeSink

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    # .env 에 AWS_PROFILE= 빈 값이 남아 있어도 멈추지 않아야 한다 (2026-10-14 ProfileNotFound)
    monkeypatch.setenv("AWS_PROFILE", "")
    with moto.mock_aws():
        LakeSink("s3://test-lake/bronze", ".", "ap-northeast-1")._client()
        s3 = boto3.client("s3", region_name="ap-northeast-1")
        s3.create_bucket(
            Bucket="test-lake",
            CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
        )
        review = {"review_id": "R-1", "created_at": "2026-10-08T23:30:00+09:00", "text": "좋아요"}
        for _ in range(2):
            sink = LakeSink("s3://test-lake/bronze", "s3://test-lake/sim-truth", "ap-northeast-1")
            sink.send(review, {"review_id": "R-1"})
            sink.close()
        keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket="test-lake")["Contents"])
        # KST 10월 8일 23:30 = UTC 10월 8일 14:30 → year=2026/month=10/day=08
        assert keys == [
            "bronze/reviews/year=2026/month=10/day=08/part-00000.jsonl",
            "sim-truth/reviews_truth/year=2026/month=10/day=08/part-00000.jsonl",
        ]
        body = s3.get_object(Bucket="test-lake", Key=keys[0])["Body"].read().decode("utf-8")
        assert [json.loads(x)["review_id"] for x in body.splitlines()] == ["R-1"]
