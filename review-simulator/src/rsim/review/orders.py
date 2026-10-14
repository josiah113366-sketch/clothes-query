"""주문(결제) 기반 리뷰 발생: 주문 읽기 → 리뷰 쓸 주문 고르기 → 1~14일 뒤 리뷰 시각 정하기.

확정한 구상 (2026-10-14, lemin)
--------------------------------
결제 시뮬레이터가 RDS 에 쌓은 결제 정보를 읽어서, 결제 후 1~14일이 지난 주문에 리뷰를 단다.
리뷰는 RDS reviews 테이블에 쓰고, 결제·회원과 같은 길(RDS → CDC → Kafka → S3)로 흘러간다.

지금(로컬 단계)은 RDS·결제 테이블이 아직 없어서 주문을 **로컬 JSONL 파일**에서 읽는다.
읽는 부분은 OrderSource 하나로 모아 두었으므로, 나중에 RDS 가 생기면
같은 모양(load() → list[Order])의 클래스를 하나 만들어 run.py 에서 바꿔 끼우면 된다.

주문 파일 형식 (.local/orders.jsonl, 한 줄에 주문 하나)
------------------------------------------------------
{"order_id": "O-1a2b3c4d5e6f", "member_id": "C-9ba27683d5", "product_id": "W-0003",
 "paid_at": "2026-10-01T13:05:00+09:00"}
- paid_at 은 시간대가 있는 ISO 시각이어야 한다(없으면 오류). DB 컬럼이 timestamptz 인 것과 맞춘다.
- product_id 는 상품 목록(catalog.py)에 있는 ID 여야 한다. 없으면 그 주문은 건너뛰고 로그에 남긴다.
- 가짜 주문 파일은 `rsim orders-fake` 로 만든다(fake_orders 함수).

같은 주문은 언제 돌려도 같은 결과
--------------------------------
"리뷰를 쓸지"와 "며칠 뒤에 쓸지"는 RANDOM_SEED 가 아니라 **order_id 만으로** 정한다.
RANDOM_SEED 를 비워 두고(매번 새 시드) 매일 돌려도 주문마다 리뷰 날짜가 바뀌지 않아야
"오늘 리뷰를 쓸 차례인 주문"을 매번 같은 기준으로 고를 수 있기 때문이다.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from ..common.rng import derive_seed, make_rng, seeded_uuid
from .catalog import Catalog

log = logging.getLogger(__name__)

# order_id 로 텀·작성 여부를 정할 때 쓰는 고정 소금값. 바꾸면 모든 주문의 리뷰 날짜가 다시 섞인다.
# (RANDOM_SEED 와 무관하게 고정. 위 "같은 주문은 언제 돌려도 같은 결과" 참고)
ORDER_HASH_SALT = 20261014


def catalog_rng() -> random.Random:
    """주문 모드에서 상품 목록을 만들 때 쓰는 고정 난수 (RANDOM_SEED 와 무관).

    data/products.csv 가 없으면 상품 목록은 시드 상품명에서 난수로 뽑아 만든다(catalog.py).
    rsim orders-fake 와 rsim run --source orders 가 같은 상품 목록을 보려면 같은 난수를 써야 한다.
    """
    return make_rng(derive_seed(ORDER_HASH_SALT, "catalog"))


@dataclass(frozen=True)
class Order:
    order_id: str
    member_id: str
    product_id: str
    paid_at: datetime  # 결제 시각 (시간대 있음)


class OrderSource(Protocol):
    """주문을 읽어 오는 곳. 지금은 JsonlOrderSource 하나, 나중에 RDS 용을 추가한다."""

    def load(self) -> list[Order]: ...


class JsonlOrderSource:
    """로컬 JSONL 파일에서 주문을 읽는다. (RDS 결제 테이블이 생기기 전까지 쓰는 임시 입력)"""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[Order]:
        if not self.path.exists():
            raise SystemExit(
                f"주문 파일이 없습니다: {self.path}\n"
                "먼저 `rsim orders-fake` 로 가짜 주문 파일을 만드세요."
            )
        orders = []
        for no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            r = json.loads(line)
            paid_at = datetime.fromisoformat(r["paid_at"])
            if paid_at.tzinfo is None:
                raise SystemExit(f"{self.path}:{no} paid_at 에 시간대가 없습니다 (예: +09:00)")
            orders.append(
                Order(
                    order_id=str(r["order_id"]),
                    member_id=str(r["member_id"]),
                    product_id=str(r["product_id"]),
                    paid_at=paid_at,
                )
            )
        return orders


# ---------------------------------------------------------------- 리뷰 발생 규칙
@dataclass(frozen=True)
class ReviewTiming:
    """주문 → 리뷰 발생 규칙. 값은 config.py(환경변수)에서 받는다.

    rate     : 주문 중 리뷰를 쓰는 비율 (0~1). 1.0 이면 모든 주문에 리뷰가 달린다.
    min_days : 결제 후 리뷰까지 최소 일수 (기본 1)
    max_days : 결제 후 리뷰까지 최대 일수 (기본 14)
    """

    rate: float = 1.0
    min_days: float = 1.0
    max_days: float = 14.0

    def _rng(self, order_id: str) -> random.Random:
        # 주문마다 따로 만드는 난수열. 같은 order_id 면 항상 같은 값이 나온다.
        return make_rng(derive_seed(ORDER_HASH_SALT, "review-timing", order_id))

    def due_at(self, order: Order) -> datetime | None:
        """이 주문의 리뷰 작성 시각. 리뷰를 쓰지 않는 주문이면 None.

        난수를 뽑는 순서(작성 여부 → 텀)는 고정이다. 순서를 바꾸면 기존 주문의 리뷰 날짜가 바뀐다.
        텀은 [min_days, max_days] 사이에서 초 단위로 고르게 뽑는다(하루 중 시각도 함께 섞인다).
        """
        rng = self._rng(order.order_id)
        if rng.random() >= self.rate:
            return None
        delay_sec = rng.uniform(self.min_days * 86400, self.max_days * 86400)
        # 초 단위로 자른다 (다른 시각 컬럼과 같은 정밀도)
        return (order.paid_at + timedelta(seconds=delay_sec)).replace(microsecond=0)


def due_orders(
    orders: Iterable[Order],
    timing: ReviewTiming,
    now: datetime,
    reviewed: set[str],
) -> list[tuple[Order, datetime]]:
    """지금 리뷰를 써야 할 주문들을 (주문, 리뷰 시각) 으로, 리뷰 시각이 빠른 순서로 돌려준다.

    조건: 리뷰를 쓰는 주문이고, 리뷰 시각 ≤ now 이고, 아직 리뷰가 없는(reviewed 에 없는) 주문.
    RDS 로 옮기면 같은 조건을 SQL 로 쓴다:
      SELECT ... FROM orders o LEFT JOIN reviews r ON r.order_id = o.order_id
      WHERE r.order_id IS NULL AND <리뷰 시각> <= now()
    (텀은 order_id 로 정해지므로 시뮬레이터가 계산해서 거른다)
    """
    picked = []
    for order in orders:
        if order.order_id in reviewed:
            continue
        due = timing.due_at(order)
        if due is not None and due <= now:
            picked.append((order, due))
    picked.sort(key=lambda x: (x[1], x[0].order_id))
    return picked


# ---------------------------------------------------------------- 가짜 주문 (rsim orders-fake)
def fake_orders(
    catalog: Catalog,
    rng: random.Random,
    start: datetime,
    days: int,
    per_day: float,
) -> list[Order]:
    """결제 시뮬레이터가 생기기 전까지 쓰는 가짜 주문.

    start 부터 days 일 동안 하루 평균 per_day 건의 결제를 포아송 간격으로 만든다.
    상품은 catalog.pick()(카테고리 비율 반영), 회원 ID 는 시드 고정 무작위 값이다.
    [임시] member_id 는 나중에 member 테이블의 실제 회원 ID 로 바뀐다.
    """
    if per_day <= 0 or days <= 0:
        return []
    end = start + timedelta(days=days)
    rate_per_sec = per_day / 86400.0
    orders = []
    t = start
    while True:
        # 지수분포 간격 = 포아송 도착 (결제가 일정 간격이 아니라 들쭉날쭉 들어오게)
        t = t + timedelta(seconds=rng.expovariate(rate_per_sec))
        if t >= end:
            break
        orders.append(
            Order(
                order_id=f"O-{seeded_uuid(rng).hex[:12]}",
                member_id=f"C-{seeded_uuid(rng).hex[:10]}",
                product_id=catalog.pick(rng).product_id,
                paid_at=t.replace(microsecond=0),
            )
        )
    return orders


def write_orders(path: Path, orders: list[Order]) -> None:
    """주문을 JSONL 로 저장한다(덮어쓰기). 형식은 JsonlOrderSource 가 읽는 것과 같다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "order_id": o.order_id,
                "member_id": o.member_id,
                "product_id": o.product_id,
                "paid_at": o.paid_at.isoformat(),
            },
            ensure_ascii=False,
        )
        for o in orders
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def run_orders_fake(
    *, out: Path | None, start: datetime, days: int, per_day: float, seed: int
) -> int:
    """rsim orders-fake 본체: 상품 목록을 만들고 가짜 주문 파일을 쓴다. 반환: 만든 주문 수."""
    from ..common.config import load_settings
    from .seeds import SeedPool

    if start.tzinfo is None:
        raise SystemExit("--start 에는 시간대를 넣어 주세요 (예: 2026-10-01T00:00:00+09:00)")
    settings = load_settings()
    # 상품명은 시드 파일에서 가져온다. rsim run --source orders 와 같은 고정 난수(catalog_rng)로 만든다
    seeds = SeedPool.load(settings.seeds_path, make_rng(0))
    catalog = Catalog.build(settings.products_path, seeds.product_names(), catalog_rng())
    orders = fake_orders(catalog, make_rng(derive_seed(seed, "orders")), start, days, per_day)
    path = out or settings.orders_path
    write_orders(path, orders)
    log.info("가짜 주문 %d건 → %s (상품 %d개)", len(orders), path, len(catalog.products))
    return len(orders)
