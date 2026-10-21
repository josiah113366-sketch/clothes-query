"""주문(결제) 기반 리뷰 발생: 주문 읽기 → 리뷰 쓸 주문 고르기 → 1~14일 뒤 리뷰 시각 정하기.

확정한 구상 (2026-10-14, lemin)
--------------------------------
결제 정보를 읽어서 결제 후 1~14일 뒤에 리뷰를 단다(하루 약 1,000건).
리뷰는 **S3 에 날짜(dt)별로 바로 쓴다.** RDS 에는 넣지 않는다(07:11 lemin 결정).
상품·회원·결제 정보가 모두 S3 에 있으므로, 조인은 S3(레이크)에서 한다.

지금(로컬 단계)은 결제 데이터가 아직 없어서 주문을 **로컬 JSONL 파일**에서 읽는다.
읽는 부분은 OrderSource 하나로 모아 두었으므로, 나중에 S3 결제 데이터를 읽을 때는
같은 모양(load() → list[Order])의 클래스를 하나 만들어 run.py 에서 바꿔 끼우면 된다.

주문 파일 형식 (.local/orders.jsonl, 한 줄에 주문 하나)
------------------------------------------------------
{"order_id": "O-1a2b3c4d5e6f", "member_id": "C-9ba27683d5", "product_id": "W-0003",
 "paid_at": "2026-10-01T13:05:00+09:00"}
- paid_at 은 시간대가 있는 ISO 시각이어야 한다(없으면 오류). 날짜 경계를 UTC 로 정확히 자르기 위해서다.
- product_id 는 상품 목록(catalog.py)에 있는 ID 여야 한다. 없으면 그 주문은 건너뛰고 로그에 남긴다.
- 가짜 주문 파일은 `rsim orders-fake` 로 만든다(fake_orders 함수).

같은 날짜는 언제 돌려도 같은 결과 (기록 조회가 필요 없는 이유)
---------------------------------------------------------------
"리뷰를 쓸지", "며칠 뒤에 쓸지", review_id 는 RANDOM_SEED 가 아니라 **order_id 만으로** 정한다.
그래서 날짜 D 를 돌리면 "리뷰 시각이 D 하루 안에 떨어지는 주문"이 항상 같은 목록으로 나온다.
결과를 날짜 D 파티션(year=/month=/day=)에 통째로 덮어쓰면, 같은 날짜를 몇 번 다시 돌려도 주문당 리뷰는 하나다.
("이미 리뷰가 있는 주문"을 따로 조회할 필요가 없다. 리뷰 문장은 LLM 이라 다시 돌리면 달라질 수 있다)
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
    """주문을 읽어 오는 곳. 지금은 JsonlOrderSource 하나, 나중에 S3 결제 데이터용을 추가한다."""

    def load(self) -> list[Order]: ...


class JsonlOrderSource:
    """로컬 JSONL 파일에서 주문을 읽는다. (결제 시뮬레이터가 S3 에 쌓기 전까지 쓰는 임시 입력)"""

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
    start: datetime,
    end: datetime,
) -> list[tuple[Order, datetime]]:
    """리뷰 시각이 [start, end) 안에 떨어지는 주문을 (주문, 리뷰 시각) 으로, 리뷰 시각 순서로 돌려준다.

    날짜 하나(D)를 돌릴 때 start = D 00:00 UTC, end = 다음 날 00:00 UTC 다.
    결제가 D-14 ~ D-1 일에 있었던 주문만 해당될 수 있으므로, 나중에 S3 결제 데이터를 읽을 때는
    그 15일치 파티션만 읽으면 된다.
    """
    picked = []
    for order in orders:
        due = timing.due_at(order)
        if due is not None and start <= due < end:
            picked.append((order, due))
    picked.sort(key=lambda x: (x[1], x[0].order_id))
    return picked


def order_id_rng(order_id: str, purpose: str = "review-ids") -> random.Random:
    """주문 모드에서 쓰는 주문별 난수 (order_id 로만 결정).

    purpose="review-ids"   : review_id·event_id
    purpose="review-attrs" : 구매 옵션·포토 여부 (options.py)
    같은 날짜를 다시 돌려도 같은 주문이면 같은 값이 나와서, 덮어쓴 결과도 ID·옵션이 바뀌지 않는다.
    """
    return make_rng(derive_seed(ORDER_HASH_SALT, purpose, order_id))


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
