"""행 오류 격리, 충돌 그룹, 연결 대기와 기존 정상 결과를 확인한다."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from pipelines.silver.transactions import build_silver, run


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


def test_cdc_uses_source_time_and_holds_equal_time_conflicts():
    first = order(status="PLACED", updated_at="2026-10-14T02:00:00+09:00",
                  __op="c", __source_ts_ms=1000, __source_snapshot=None)
    later = order(status="PAID", updated_at="2026-10-14T01:00:00+09:00",
                  __op="u", __source_ts_ms=2000, __source_snapshot=None)
    result = build_silver([later, first, dict(later)], [], [])
    assert result["orders_current"][0]["status"] == "PAID"
    assert [row["status"] for row in result["order_status_history"]] == ["PLACED", "PAID"]
    assert summary(result, "orders")["duplicate_count"] == 1
    clash = {**later, "__source_ts_ms": 1000}
    blocked = build_silver([first, clash], [], [])
    assert not blocked["orders_current"]
    assert {row["error_code"] for row in blocked["quarantined_records"]} == {"CONTENT_CONFLICT"}
    deleted = build_silver([{**first, "__op": "d"}], [], [])
    assert deleted["quarantined_records"][0]["error_code"] == "UNSUPPORTED_CDC"


def test_flat_cdc_file_loading_keeps_every_conflict_candidate(tmp_path):
    source, target = tmp_path / "input", tmp_path / "silver"
    source.mkdir()
    rows = {
        "orders": [order(__op="r", __source_ts_ms=1000)],
        "items": [{"order_item_id": "I1", "order_id": "O-1", "article_id": "0001",
                   "quantity": 1, "unit_price": 1000, "__op": "r", "__source_ts_ms": 1000}],
        "payments": [payment(__op="c", __source_ts_ms=2000),
                     payment(amount=2000, __op="c", __source_ts_ms=2000)],
    }
    for name, values in rows.items():
        (source / (name + ".json")).write_text(
            "".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")
    manifest = run(*(str(source / (name + ".json")) for name in rows), str(target), input_complete=True)
    assert manifest["status"] == "INCOMPLETE"
    assert manifest["input_completeness"] == "DECLARED_COMPLETE"
    candidates = [json.loads(line) for line in Path(manifest["outputs"]["impact_candidates"]).read_text(
        encoding="utf-8").splitlines()]
    assert len([row for row in candidates if row["source_dataset"] == "payments"]) == 2
    assert all("member_id" not in row for row in candidates)
    assert all("source" in row for row in candidates)


def test_order_item_sum_requires_complete_input_and_counts_duplicates_once():
    item = {"order_item_id": "I1", "order_id": "O-1", "article_id": "0001",
            "quantity": 2, "unit_price": 500}
    unchecked = build_silver([order(total_amount=1200)], [item], [], input_complete=False)
    assert summary(unchecked, "orders")["amount_checks"][0]["status"] == "UNVERIFIED"
    assert not unchecked["quarantined_records"]
    passed = build_silver([order()], [item, dict(item)], [payment()], input_complete=True)
    assert summary(passed, "orders")["amount_checks"][0]["item_total_amount"] == 1000
    assert summary(passed, "orders")["amount_checks"][0]["status"] == "PASS"
    assert len(passed["orders_current"]) == 1
    result = build_silver([order(total_amount=1200), order("O-2")],
                         [item, {**item, "order_item_id": "I2", "order_id": "O-2"}],
                         [payment(amount=1200), payment("P2", order_id="O-2")], input_complete=True)
    assert [row["order_id"] for row in result["orders_current"]] == ["O-2"]
    assert [row["order_id"] for row in result["order_status_history"]] == ["O-2"]
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["P2"]
    issue = next(row for row in result["quarantined_records"] if row["error_code"] == "ORDER_TOTAL_MISMATCH")
    assert (issue["order_total_amount"], issue["item_total_amount"], issue["amount_difference"]) == (1200, 1000, -200)


def test_missing_or_invalid_items_do_not_become_zero_or_partial_sum_mismatches():
    missing = build_silver([order()], [], [payment()], input_complete=True)
    assert not missing["orders_current"] and not missing["payment_attempts"]
    assert summary(missing, "orders")["amount_checks"][0]["status"] == "PENDING_REFERENCE"
    assert all(row["error_code"] != "ORDER_TOTAL_MISMATCH" for row in missing["quarantined_records"])
    item = {"order_item_id": "I1", "order_id": "O-1", "article_id": "0001",
            "quantity": 1, "unit_price": 500}
    broken = build_silver([order()], [item, {**item, "order_item_id": "I2", "unit_price": 0}],
                          [payment()], input_complete=True)
    check = summary(broken, "orders")["amount_checks"][0]
    assert check["status"] == "ITEM_ERROR" and "item_total_amount" not in check
    assert not broken["orders_current"]


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


def test_local_files_reexecution_and_failed_publish_preserve_previous_result(tmp_path, monkeypatch):
    inputs = tmp_path / "input"
    inputs.mkdir()
    orders = inputs / "orders.jsonl"
    items = inputs / "items.jsonl"
    payments = inputs / "payments.jsonl"
    orders.write_text(json.dumps(order()) + "\n", encoding="utf-8")
    items.write_text("", encoding="utf-8")
    # 정상 결제 재수신과 깨진 JSON이 함께 있어도 원본 위치와 불완전 상태를 남긴다.
    payments.write_text((json.dumps(payment()) + "\n") * 2 + "broken-json\n", encoding="utf-8")
    output = tmp_path / "output"
    args = (str(orders), str(items), str(payments), str(output))
    first = run(*args)
    assert first["status"] == "INCOMPLETE"
    assert first["output_counts"]["payment_attempts"] == 1
    issues = [json.loads(line) for line in Path(first["outputs"]["quarantined_records"]).read_text(encoding="utf-8").splitlines()]
    assert (issues[0]["source_file"], issues[0]["source_line"], issues[0]["error_code"]) == (
        str(payments.resolve()), 3, "PARSE_ERROR",
    )
    second = run(*args)
    assert first["output_counts"] == second["output_counts"]
    for name in first["outputs"]:
        assert Path(first["outputs"][name]).read_bytes() == Path(second["outputs"][name]).read_bytes()
    manifest = Path(second["manifest_path"])
    previous = manifest.read_bytes()
    with pytest.raises(FileNotFoundError):
        run(str(inputs / "missing.jsonl"), *args[1:])
    assert manifest.read_bytes() == previous

    write_text = Path.write_text

    def fail_payment_write(path, *args, **kwargs):
        if path.name == "payment_attempts.jsonl":
            raise OSError("simulated storage failure")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_payment_write)
    with pytest.raises(OSError):
        run(*args)
    assert manifest.read_bytes() == previous
    assert len(list((output / "silver" / "transactions" / "runs").iterdir())) == 2


def test_document_input_does_not_silently_interpret_cdc_or_overwrite_source(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps({"op": "c", "after": order()}) + "\n", encoding="utf-8")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="CDC"):
        run(str(source), str(source), str(source), str(output))
    assert not output.exists()
    with pytest.raises(ValueError, match="겹치지"):
        run(str(source), str(source), str(source), str(tmp_path))
