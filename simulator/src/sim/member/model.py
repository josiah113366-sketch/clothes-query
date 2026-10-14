from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, repr=False)
class NewMember:
    """새 회원 한 명 (created_at 제외). PII가 새지 않게 repr은 member_id만 보여 준다."""

    member_id: str
    name: str
    email: str
    phone: str
    birth_date: date
    password_hash: str
    gender: str
    signup_at: datetime
    signup_channel: str
    marketing_consent: bool
    status: str
    withdrawn_at: datetime | None
    region_sigungu: str
    age_band: str

    def __repr__(self) -> str:
        return f"NewMember(member_id={self.member_id!r})"
