"""결제 업무 내용의 공통 지문. 입력 정책 검사·원본 위치·호출 경로와 독립적이다.

호출자는 공통 입력 검사를 먼저 수행하고, 시각 변환 전의 원천 문자열을 전달한다.
정책상 허용 코드 목록이나 PG 목록을 이 파일에 중복 정의하지 않는다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256

FINGERPRINT_VERSION = "payment-content.v1"
CONTENT_FIELDS = ("order_id", "attempt_no", "method", "pg", "amount", "status",
                  "failure_code", "requested_at", "completed_at")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                   r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})")


class FingerprintError(ValueError):
    """입력값을 노출하지 않고 지문을 만들 수 없는 필드명만 전달한다."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"결제 지문 입력 오류: {field}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FingerprintError(field)
    return value


def _utc_time(value: object, field: str) -> str:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        # 7자리 이상 소수초를 datetime이 조용히 절삭하지 못하게 먼저 제한한다.
        raise FingerprintError(field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise FingerprintError(field) from None
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_payment_content(payment: Mapping[str, object]) -> bytes:
    """고정 순서 JSON 배열을 UTF-8로 반환한다. 원본 객체를 수정하지 않는다.

    payment_id와 Kafka/CDC/적재 메타데이터는 포함하지 않는다. UTC 정규화 외에는
    숫자 변환·문자열 trim/대소문자 변환은 하지 않는다. 유일한 생략 정규화는
    SUCCESS의 failure_code 생략 → null이다. 시각 변환 후의 손실된 값은 전달하지 않는다.
    """
    if not isinstance(payment, Mapping):
        raise FingerprintError("record")
    for field in CONTENT_FIELDS:
        if field not in payment:
            if field == "failure_code" and payment.get("status") == "SUCCESS":
                continue
            raise FingerprintError(field)
    values = []
    for field in CONTENT_FIELDS:
        value = payment.get(field) if field == "failure_code" else payment[field]
        if field in {"attempt_no", "amount"}:
            if type(value) is not int or value < 1:
                raise FingerprintError(field)
        elif field in {"requested_at", "completed_at"}:
            value = _utc_time(value, field)
        elif field == "failure_code":
            if value is not None:
                value = _text(value, field)
        else:
            value = _text(value, field)
        values.append(value)
    if payment["status"] not in ("SUCCESS", "FAILED"):
        raise FingerprintError("status")
    if ((payment["status"] == "SUCCESS" and payment.get("failure_code") is not None)
            or (payment["status"] == "FAILED" and payment.get("failure_code") is None)):
        raise FingerprintError("failure_code")
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def payment_fingerprint(payment: Mapping[str, object]) -> dict[str, str]:
    """양쪽 원장/결과에 붙일 내용 해시와 규칙 버전을 반환한다."""
    return {"payment_content_hash": sha256(canonical_payment_content(payment)).hexdigest(),
            "fingerprint_version": FINGERPRINT_VERSION}
