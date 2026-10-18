"""행동 시뮬레이터의 값들. 모두 불변 데이터 클래스다. 회원 값(PII)은 담지 않는다."""

from dataclasses import dataclass
from datetime import datetime

# 주문 상태
PLACED = "PLACED"
PAID = "PAID"
SHIPPED = "SHIPPED"
DELIVERED = "DELIVERED"
PAYMENT_FAILED = "PAYMENT_FAILED"
CANCELLED = "CANCELLED"
REFUNDED = "REFUNDED"
TERMINAL_STATES = frozenset({PAYMENT_FAILED, CANCELLED, REFUNDED})

# 결제 시도 결과
SUCCESS = "SUCCESS"
FAILED = "FAILED"

# 클릭 종류
VIEW = "view"
CART_ADD = "cart_add"


@dataclass(frozen=True)
class Catalog:
    """상품 목록 (article_id 순). 인덱스로 가리킨다."""

    article_ids: tuple[str, ...]
    prices: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.article_ids)


@dataclass(frozen=True)
class ClickEvent:
    event_id: str
    event_type: str  # "view" | "cart_add"
    member_id: str
    article_id: str
    event_time: datetime
    session_id: str


@dataclass(frozen=True)
class NewOrder:
    order_id: str
    member_id: str
    session_id: str
    status: str
    status_reason: str | None
    total_amount: int
    ordered_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NewOrderItem:
    order_item_id: str
    order_id: str
    article_id: str
    quantity: int
    unit_price: int


@dataclass(frozen=True)
class NewPayment:
    payment_id: str
    order_id: str
    attempt_no: int
    method: str
    pg: str
    amount: int
    status: str
    failure_code: str | None
    requested_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class OrderPlan:
    order: NewOrder
    items: tuple[NewOrderItem, ...]
    method: str
    first_attempt_at: datetime  # 결제 전 취소면 쓰지 않는다
    cancel_at: datetime | None  # 결제 전 취소로 정해졌으면 그 시각


@dataclass(frozen=True)
class VisitPlan:
    visit_no: int
    session_id: str
    member_id: str
    arrived_at: datetime
    clicks: tuple[ClickEvent, ...]  # 시각 순
    order: OrderPlan | None


@dataclass(frozen=True)
class AttemptResult:
    pg: str
    status: str
    failure_code: str | None
    requested_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class Transition:
    status: str
    status_reason: str | None
    at: datetime


# --- 큐 항목 ---


@dataclass(frozen=True)
class OrderRef:
    """큐 항목이 주문에 대해 알아야 하는 것. visit_no는 후속 추첨의 시드에 쓴다."""

    order_id: str
    visit_no: int
    method: str
    amount: int


@dataclass(frozen=True)
class ClickTask:
    event: ClickEvent


@dataclass(frozen=True)
class CreateOrderTask:
    plan: OrderPlan
    visit_no: int


@dataclass(frozen=True)
class AttemptStartTask:
    ref: OrderRef
    attempt_no: int
    previous_pg: str | None


@dataclass(frozen=True)
class AttemptDoneTask:
    ref: OrderRef
    payment: NewPayment


@dataclass(frozen=True)
class TransitionTask:
    ref: OrderRef
    transition: Transition


Task = ClickTask | CreateOrderTask | AttemptStartTask | AttemptDoneTask | TransitionTask
