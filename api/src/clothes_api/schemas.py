"""요청 본문. 필드 이름은 DB 컬럼 그대로다(db/schema/001_member.sql, 004_orders.sql).

검증은 DB 제약과 같게 한다. DB가 마지막 방어선이다. 시각은 시간대가 있는 값만 받는다.
"""

from datetime import UTC, date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Gender = Literal["F", "M"]
AgeBand = Literal["~19", "20s", "30s", "40s", "50s", "60s", "70+"]
SignupChannel = Literal["web", "app"]
OrderStatus = Literal[
    "PLACED", "PAID", "SHIPPED", "DELIVERED", "PAYMENT_FAILED", "CANCELLED", "REFUNDED"
]
UpdatableStatus = Literal["PAID", "SHIPPED", "DELIVERED", "PAYMENT_FAILED", "CANCELLED", "REFUNDED"]
PaymentMethod = Literal["CARD", "SIMPLE_PAY", "BANK_TRANSFER"]
Pg = Literal["PG_A", "PG_B"]
PaymentStatus = Literal["SUCCESS", "FAILED"]
FailureCode = Literal[
    "INSUFFICIENT_BALANCE", "CARD_LIMIT_EXCEEDED", "CARD_DECLINED", "PG_TIMEOUT", "PG_ERROR"
]
ClickType = Literal["view", "cart_add"]

# 상태와 사유는 짝이다 (004_orders.sql orders_status_reason_check)
STATUS_REASON: dict[str, str] = {"CANCELLED": "USER_REQUEST", "REFUNDED": "RETURN"}
MAX_CLICKS_PER_REQUEST = 500


def utc_z(value: datetime) -> str:
    """UTC ISO 8601, `Z`로 끝난다 (시뮬레이터·Debezium 표기와 같다)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewMember(_Strict):
    member_id: UUID
    name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    phone: str = Field(min_length=1)
    birth_date: date
    password_hash: str = Field(min_length=1)
    gender: Gender
    age_band: AgeBand
    region_sigungu: str = Field(min_length=1)
    signup_channel: SignupChannel
    marketing_consent: bool
    signup_at: AwareDatetime

    def __repr__(self) -> str:  # PII가 출력에 섞이지 않게 한다
        return f"NewMember(member_id={self.member_id})"

    __str__ = __repr__


class NewOrderItem(_Strict):
    order_item_id: UUID
    article_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    unit_price: int = Field(gt=0)


class NewOrder(_Strict):
    order_id: UUID
    member_id: UUID
    session_id: UUID
    status: Literal["PLACED"] = "PLACED"
    total_amount: int = Field(gt=0)
    ordered_at: AwareDatetime
    items: list[NewOrderItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.total_amount != sum(i.quantity * i.unit_price for i in self.items):
            raise ValueError("total_amount는 항목 합계(수량×단가)와 같아야 합니다")
        articles = [i.article_id for i in self.items]
        if len(set(articles)) != len(articles):
            raise ValueError("한 주문 안에서 article_id가 겹칩니다")
        item_ids = [i.order_item_id for i in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("order_item_id가 겹칩니다")
        return self


class NewPayment(_Strict):
    payment_id: UUID
    attempt_no: int = Field(ge=1)
    method: PaymentMethod
    pg: Pg
    amount: int = Field(gt=0)
    status: PaymentStatus
    failure_code: FailureCode | None = None
    requested_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.status == "SUCCESS") != (self.failure_code is None):
            raise ValueError("SUCCESS면 failure_code가 없고, FAILED면 있어야 합니다")
        if self.completed_at < self.requested_at:
            raise ValueError("completed_at은 requested_at 이후여야 합니다")
        return self


class StatusUpdate(_Strict):
    status: UpdatableStatus
    status_reason: str | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _reason(self) -> Self:
        if self.status_reason != STATUS_REASON.get(self.status):
            raise ValueError("status_reason이 상태와 맞지 않습니다")
        return self


class ClickEvent(_Strict):
    event_id: str = Field(min_length=1)
    event_type: ClickType
    member_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    event_time: AwareDatetime
    session_id: str = Field(min_length=1)

    def record(self) -> dict[str, str]:
        """clickstream 메시지 값. 시뮬레이터 click_record와 같은 6필드다."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "member_id": self.member_id,
            "article_id": self.article_id,
            "event_time": utc_z(self.event_time),
            "session_id": self.session_id,
        }


class ClickBatch(_Strict):
    # 상한(500)은 라우트에서 413으로 거절한다
    events: list[ClickEvent] = Field(min_length=1)
