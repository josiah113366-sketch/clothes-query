"""행 오류 격리, 충돌 그룹, 연결 대기와 기존 정상 결과를 확인한다."""

from copy import deepcopy

from pipelines.silver.transactions import build_silver


def order(identifier="O-1", **changes):
    return {
        "order_id": identifier, "member_id": "M-test", "session_id": "S-test",
        "status": "PLACED", "status_reason": None, "total_amount": 1000,
        "ordered_at": "2026-10-14T00:00:00+09:00",
        "updated_at": "2026-10-14T00:00:00+09:00", **changes,
    }


def payment(identifier="P-1", **changes):
    return {
        "payment_id": identifier, "order_id": "O-1", "attempt_no": 1,
        "method": "CARD", "pg": "PG_A", "amount": 1000,
        "status": "SUCCESS", "failure_code": None,
        "requested_at": "2026-10-14T00:01:00+09:00",
        "completed_at": "2026-10-14T00:02:00+09:00", **changes,
    }


def summary(result, name):
    return next(row for row in result["dq_results"] if row["source_dataset"] == name)


def test_bad_payment_does_not_stop_normal_orders_and_reexecution():
    orders = [order(), order("O-2")]
    payments = [
        payment(),
        payment("P-2", order_id="O-2", status="FAILED"),  # 필수 실패 코드 없음
    ]
    result = build_silver(orders, [], payments)
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["P-1"]
    assert len(result["orders_current"]) == 2
    issue = result["quarantined_records"][0]
    assert (issue["record_key"], issue["field"], issue["error_code"]) == (
        "P-2", "failure_code", "MISSING_FIELD",
    )
    quality = summary(result, "payments")
    assert (quality["input_count"], quality["accepted_count"], quality["quarantined_count"]) == (2, 1, 1)
    assert quality["status"] == "INCOMPLETE"
    assert quality["affected_order_ids"] == ["O-2"]
    assert result == build_silver(deepcopy(orders), [], deepcopy(payments))
    assert "raw_data" not in issue


def test_duplicate_conflict_retry_and_invalid_duplicate_are_distinct():
    first = payment()
    clash = payment("P-conflict", order_id="O-2", status="FAILED", failure_code="PG_TIMEOUT")
    invalid = payment("P-invalid", order_id="O-3")
    result = build_silver(
        [order(), order("O-2"), order("O-3")], [],
        [first, dict(first),
         payment("P-retry", status="FAILED", failure_code="PG_ERROR", attempt_no=2),
         clash, {**clash, "failure_code": "PG_ERROR"},
         invalid, {**invalid, "status": "FAILED"}],
    )
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["P-1", "P-retry"]
    quality = summary(result, "payments")
    assert quality["duplicate_count"] == 1
    assert quality["conflict_count"] == 2
    assert quality["quarantined_count"] == 4
    assert quality["input_count"] == sum(quality[key] for key in (
        "accepted_count", "duplicate_count", "quarantined_count",
    ))


def test_missing_order_is_pending_and_broken_order_does_not_publish_stale_state():
    result = build_silver(
        [order(), order(status="BAD", updated_at="2026-10-14T01:00:00+09:00")],
        [], [payment(), payment("P-missing", order_id="O-missing")],
    )
    assert result["orders_current"] == []
    assert result["order_status_history"] == []
    assert result["payment_attempts"] == []
    issues = {row["record_key"]: row for row in result["quarantined_records"] if row["source_dataset"] == "payments"}
    assert issues["P-1"]["category"] == "DEPENDENCY_BLOCKED"
    assert issues["P-missing"]["category"] == "PENDING_REFERENCE"


def test_retry_sequence_and_amount_failures_do_not_remove_unrelated_success():
    result = build_silver(
        [order(), order("O-2"), order("O-3"), order("O-4")], [],
        [payment(), payment("P-a", order_id="O-2"), payment("P-b", order_id="O-2"),
         payment("P-amount", order_id="O-3", amount=500),
         payment("P-s1", order_id="O-4"), payment("P-s2", order_id="O-4", attempt_no=2)],
    )
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["P-1"]
    codes = {row["error_code"] for row in result["quarantined_records"]}
    assert codes == {"ATTEMPT_CONFLICT", "AMOUNT_MISMATCH", "MULTIPLE_SUCCESSES"}


def test_history_item_totals_and_invalid_shapes():
    item = {"order_item_id": "I-1", "order_id": "O-1", "article_id": "A-1", "quantity": 2, "unit_price": 500}
    result = build_silver(
        [order(), order(status="PAID", updated_at="2026-10-14T00:02:00+09:00")],
        [item, dict(item), {**item, "order_item_id": "I-bad", "unit_price": 0}],
        [payment(), "not-an-object"],
    )
    assert result["orders_current"][0]["status"] == "PAID"
    assert len(result["order_status_history"]) == 2
    assert result["silver_order_items"][0]["item_amount"] == 1000
    assert summary(result, "order_items")["duplicate_count"] == 1
    assert summary(result, "orders")["status"] == "PASS"
    assert summary(result, "payments")["status"] == "INCOMPLETE"
    assert build_silver([], [], [])["quarantined_records"] == []
