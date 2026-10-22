"""신규 가입을 업무 API로 보낸다(MemberStore 구현). DB 계정이 필요 없다.

회원 값(PII)은 요청 본문에만 싣고 출력하지 않는다. status·withdrawn_at·created_at은 API가 채운다.
"""

from datetime import datetime

from sim.common.api import ApiClient
from sim.member.model import NewMember

# API가 받는 가입 필드 (api/src/clothes_api/schemas.py NewMember)
SIGNUP_FIELDS = (
    "member_id", "name", "email", "phone", "birth_date", "password_hash", "gender",
    "age_band", "region_sigungu", "signup_channel", "marketing_consent", "signup_at",
)  # fmt: skip


class ApiStore:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def connect(self) -> None:
        self._client.health()

    def close(self) -> None:
        pass

    def count_since(self, since: datetime) -> int:
        body = self._client.get(
            "/v1/members/signup-count",
            {"from": since.isoformat()},
        )
        return int(body["count"])

    def insert(self, member: NewMember) -> None:
        """201(생성)·200(같은 내용이 이미 있음) 모두 성공. 전화 중복은 PhoneTaken."""
        self._client.request("POST", "/v1/members", {f: getattr(member, f) for f in SIGNUP_FIELDS})
