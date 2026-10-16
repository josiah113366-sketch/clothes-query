"""문서에 합의된 주문·주문상품·결제 행을 Silver 분석 기준으로 바꾼다.

입력은 CDC 봉투가 아닌 변경 후 비즈니스 컬럼이다. 실제 Bronze 경로·JSON
모양을 확인한 뒤 별도 입력 어댑터로 연결한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ORDER_STATUSES = {
    "PLACED", "PAID", "SHIPPED", "DELIVERED",
    "PAYMENT_FAILED", "CANCELLED", "REFUNDED",
}


def _required_text(row: dict, field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}가 비어 있습니다")
    return value


def _time(row: dict, field: str) -> datetime:
    value = _required_text(row, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}는 ISO 시각이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}에 시간대가 없습니다")
    return parsed.astimezone(UTC)


def _integer(row: dict, field: str, minimum: int) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field}는 {minimum} 이상의 정수여야 합니다")
    return value


def _unique_rows(rows: list[dict], key: str) -> list[dict]:
    selected: dict[str, dict] = {}
    for row in rows:
        identifier = _required_text(row, key)
        previous = selected.get(identifier)
        if previous is not None and previous != row:
            raise ValueError(f"{key}가 같은 서로 다른 행이 있습니다")
        selected[identifier] = row
    return [selected[identifier] for identifier in sorted(selected)]


def build_silver(
    orders: list[dict], order_items: list[dict], payments: list[dict]
) -> dict[str, list[dict]]:
    """가상 입력으로 검증할 순수 계산. 실제 Bronze 파일은 아직 읽지 않는다."""
    by_order: dict[str, list[dict]] = {}
    for raw in orders:
        order_id = _required_text(raw, "order_id")
        status = _required_text(raw, "status")
        if status not in ORDER_STATUSES:
            raise ValueError("지원하지 않는 주문 상태입니다")
        ordered = _time(raw, "ordered_at")
        updated = _time(raw, "updated_at")
        if updated < ordered:
            raise ValueError("updated_at이 ordered_at보다 빠릅니다")
        row = {
            "order_id": order_id,
            "member_id": _required_text(raw, "member_id"),
            "session_id": _required_text(raw, "session_id"),
            "status": status,
            "status_reason": raw.get("status_reason"),
            "total_amount": _integer(raw, "total_amount", 0),
            "ordered_at_utc": ordered.isoformat(),
            "ordered_at_kst": ordered.astimezone(KST).isoformat(),
            "updated_at_utc": updated.isoformat(),
            "updated_at_kst": updated.astimezone(KST).isoformat(),
        }
        by_order.setdefault(order_id, []).append(row)

    current: list[dict] = []
    history: list[dict] = []
    for order_id in sorted(by_order):
        events = sorted(by_order[order_id], key=lambda row: row["updated_at_utc"])
        previous: dict | None = None
        for row in events:
            if previous and row["updated_at_utc"] == previous["updated_at_utc"]:
                if row != previous:
                    raise ValueError("같은 주문의 동일 변경 시각에 서로 다른 상태가 있습니다")
                continue
            if previous is None or row["status"] != previous["status"]:
                history.append({
                    "order_id": order_id,
                    "previous_status": None if previous is None else previous["status"],
                    "status": row["status"],
                    "status_reason": row["status_reason"],
                    "changed_at_utc": row["updated_at_utc"],
                    "changed_at_kst": row["updated_at_kst"],
                })
            previous = row
        current.append(events[-1])

    items: list[dict] = []
    for raw in order_items:
        ordered_id = _required_text(raw, "order_id")
        if ordered_id not in by_order:
            raise ValueError("주문상품이 연결할 주문이 없습니다")
        quantity = _integer(raw, "quantity", 1)
        unit_price = _integer(raw, "unit_price", 0)
        items.append({
            "order_item_id": _required_text(raw, "order_item_id"),
            "order_id": ordered_id,
            "article_id": _required_text(raw, "article_id"),
            "quantity": quantity,
            "unit_price": unit_price,
            "item_amount": quantity * unit_price,
        })
    items = _unique_rows(items, "order_item_id")

    attempts: list[dict] = []
    for raw in payments:
        order_id = _required_text(raw, "order_id")
        if order_id not in by_order:
            raise ValueError("결제 시도가 연결할 주문이 없습니다")
        status = _required_text(raw, "status")
        if status not in {"SUCCESS", "FAILED"}:
            raise ValueError("지원하지 않는 결제 결과입니다")
        requested = _time(raw, "requested_at")
        completed = _time(raw, "completed_at")
        if completed < requested:
            raise ValueError("결제 완료 시각이 요청 시각보다 빠릅니다")
        attempts.append({
            "payment_id": _required_text(raw, "payment_id"),
            "order_id": order_id,
            "attempt_no": _integer(raw, "attempt_no", 1),
            "method": _required_text(raw, "method"),
            "pg": _required_text(raw, "pg"),
            "amount": _integer(raw, "amount", 0),
            "status": status,
            "failure_code": raw.get("failure_code"),
            "requested_at_utc": requested.isoformat(),
            "requested_at_kst": requested.astimezone(KST).isoformat(),
            "completed_at_utc": completed.isoformat(),
            "completed_at_kst": completed.astimezone(KST).isoformat(),
        })
    attempts = _unique_rows(attempts, "payment_id")

    success_by_order: dict[str, dict] = {}
    current_by_id = {row["order_id"]: row for row in current}
    for attempt in attempts:
        if attempt["status"] != "SUCCESS":
            continue
        order_id = attempt["order_id"]
        if order_id in success_by_order:
            raise ValueError("한 주문에 성공 결제가 두 건 있습니다")
        if attempt["amount"] != current_by_id[order_id]["total_amount"]:
            raise ValueError("성공 결제 금액과 주문 금액이 다릅니다")
        success_by_order[order_id] = attempt

    return {
        "orders_current": current,
        "order_status_history": history,
        "silver_order_items": items,
        "payment_attempts": attempts,
    }
