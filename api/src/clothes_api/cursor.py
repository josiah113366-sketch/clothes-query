"""목록·변경분 커서. 클라이언트에게는 불투명한 문자열이다(base64url JSON)."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from clothes_api.errors import unprocessable

# 동시에 처리된 요청은 늦게 커밋될 수 있다. 커서보다 이만큼 앞부터 겹쳐 돌려주고
# 클라이언트(시뮬레이터)가 중복을 버린다.
CHANGES_OVERLAP = timedelta(seconds=10)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ChangesCursor:
    created_at: datetime

    def encode(self) -> str:
        raw = json.dumps({"t": self.created_at.astimezone(UTC).isoformat()}).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @property
    def query_from(self) -> datetime:
        return self.created_at - CHANGES_OVERLAP


def decode_changes(token: str) -> ChangesCursor:
    try:
        padded = token + "=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(data["t"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise unprocessable("BAD_CURSOR", "after 커서를 읽을 수 없습니다") from None
    if created_at.tzinfo is None:
        raise unprocessable("BAD_CURSOR", "after 커서를 읽을 수 없습니다")
    return ChangesCursor(created_at)


def encode_key(value: str) -> str:
    """페이지 커서: 마지막으로 보낸 키(member_id, article_id)."""
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode_key(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return base64.urlsafe_b64decode((token + "=" * (-len(token) % 4)).encode()).decode()
    except (ValueError, binascii.Error):
        raise unprocessable("BAD_CURSOR", "cursor를 읽을 수 없습니다") from None
