"""행 오류 격리, 충돌 그룹, 연결 대기와 기존 정상 결과를 확인한다."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import yaml

from pipelines.format_rules import (
    DEFAULT_RULES,
    FormatError,
    FormatRules,
    RuleConfigError,
)
from pipelines.silver.transactions import build_silver, run


def fixture_id(label):
    if not isinstance(label, str):
        return label
    try:
        UUID(label)
    except ValueError:
        return str(uuid5(NAMESPACE_URL, label))
    return label


def order(identifier="00000000-4000-8000-0000-000000000009", **changes):
    return {
        "order_id": fixture_id(identifier), "member_id": "00000000-4000-8000-0000-000000000008", "session_id": "00000000-4000-8000-0000-00000000001f",
        "status": "PLACED", "status_reason": None, "total_amount": 1000,
        "ordered_at": "2026-10-14T00:00:00+09:00",
        "updated_at": "2026-10-14T00:00:00+09:00", **changes,
    }


def payment(identifier="00000000-4000-8000-0000-000000000011", **changes):
    return {
        "payment_id": fixture_id(identifier), "order_id": "00000000-4000-8000-0000-000000000009", "attempt_no": 1,
        "method": "CARD", "pg": "PG_A", "amount": 1000,
        "status": "SUCCESS", "failure_code": None,
        "requested_at": "2026-10-14T00:01:00+09:00",
        "completed_at": "2026-10-14T00:02:00+09:00", **changes,
    }


def summary(result, name):
    return next(row for row in result["dq_results"] if row["source_dataset"] == name)


def test_yaml_contract_validates_uuid_enums_reasons_and_times():
    rules = FormatRules()
    cases = [
        ("orders", order(order_id="not-a-uuid"), "order_id", "INVALID_VALUE"),
        ("orders", order(status="CANCELLED"), "status_reason", "INVALID_VALUE"),
        ("orders", order(status="PLACED", status_reason="RETURN"), "status_reason", "INVALID_VALUE"),
        ("payments", payment(pg="PG_NEW"), "pg", "INVALID_VALUE"),
        ("payments", payment(method="CHEQUE"), "method", "INVALID_VALUE"),
        ("payments", payment(amount=True), "amount", "TYPE_MISMATCH"),
        ("payments", payment(completed_at="2026-10-14T00:00:00+09:00"), "completed_at", "INVALID_VALUE"),
        ("payments", payment(completed_at="2026-10-14T00:02:00"), "completed_at", "INVALID_VALUE"),
    ]
    for dataset, row, field, code in cases:
        with pytest.raises(FormatError) as caught:
            rules.validate(dataset, row)
        assert (caught.value.field, caught.value.code) == (field, code)
        assert caught.value.rule_id
    rules.validate("orders", order(status="CANCELLED", status_reason="USER_REQUEST"))
    rules.validate("orders", order(status="REFUNDED", status_reason="RETURN"))


def test_yaml_is_the_executed_rule_source_and_proposals_are_not_applied(tmp_path):
    document = yaml.safe_load(DEFAULT_RULES.read_text(encoding="utf-8"))
    item = {"order_item_id": fixture_id("rule-item"), "order_id": order()["order_id"],
            "article_id": "0001", "quantity": 2, "unit_price": 500}
    document["source_rules"]["order_items"]["fields"]["quantity"]["minimum"] = 3
    custom = tmp_path / "rules.yaml"
    custom.write_text(yaml.safe_dump(document), encoding="utf-8")
    rules = FormatRules(custom)
    result = build_silver([order()], [item], [], rules=rules)
    issue = result["quarantined_records"][0]
    assert (issue["error_code"], issue["rule_id"]) == ("INVALID_VALUE", "order_items.fields.quantity.minimum")
    assert result["dq_results"][0]["format_rules"] == rules.reference()
    assert rules.digest != FormatRules().digest
    # YAML에 미등록 허용 제안이 있어도 실제 enum 검사는 계속 실행된다.
    failed = build_silver([order()], [], [payment(status="FAILED", failure_code="PG_NEW_ERROR")], rules=rules)
    assert failed["quarantined_records"][0]["rule_id"] == "payments.fields.failure_code.enum"


def test_invalid_yaml_stops_run_preserves_previous_and_records_applied_hash(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    for name, values in (("orders", [order()]), ("items", []), ("payments", [payment()])):
        (source / (name + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")
    args = [str(source / (name + ".jsonl")) for name in ("orders", "items", "payments")] + [str(tmp_path / "output")]
    manifest = run(*args)
    pointer = Path(manifest["manifest_path"])
    previous = pointer.read_bytes()
    assert manifest["format_rules"] == FormatRules().reference()
    original = yaml.safe_load(DEFAULT_RULES.read_text(encoding="utf-8"))
    unsupported = deepcopy(original)
    unsupported["source_rules"]["orders"]["checks"][0]["rule"] = "unsupported"
    disconnected = deepcopy(original)
    disconnected["runtime_connected"]["silver"] = False
    bad_condition = deepcopy(original)
    bad_condition["source_rules"]["orders"]["checks"][1]["when"]["equals"] = "CANCLED"
    custom = tmp_path / "rules.yaml"
    for body in ("[broken", "version: first\nversion: second\n",
                 yaml.safe_dump(unsupported), yaml.safe_dump(disconnected), yaml.safe_dump(bad_condition)):
        custom.write_text(body, encoding="utf-8")
        with pytest.raises(RuleConfigError):
            run(*args, rules_path=str(custom))
        assert pointer.read_bytes() == previous
    with pytest.raises(FileNotFoundError):
        run(*args, rules_path=str(tmp_path / "missing.yaml"))
    assert pointer.read_bytes() == previous


def test_failure_codes_follow_source_allowlist_and_preserve_valid_failed_attempts():
    codes = ["INSUFFICIENT_BALANCE", "CARD_LIMIT_EXCEEDED", "CARD_DECLINED", "PG_TIMEOUT", "PG_ERROR"]
    payments = [payment("P" + str(index), attempt_no=index + 1, status="FAILED", failure_code=code)
                for index, code in enumerate(codes)]
    result = build_silver([order()], [], payments)
    assert not result["quarantined_records"]
    assert {row["failure_code"] for row in result["payment_attempts"]} == set(codes)
    assert summary(result, "payments")["failure_code_policy"] == "format_rules:0.1.0"


def test_missing_unknown_and_non_string_failure_codes_have_distinct_errors():
    cases = [(None, "MISSING_FIELD"), ("", "MISSING_FIELD"), ("  ", "MISSING_FIELD"),
             (123, "TYPE_MISMATCH"), ("PG_NEW_ERROR", "INVALID_VALUE"),
             ("UNKNOWN", "INVALID_VALUE"), (" PG_TIMEOUT ", "INVALID_VALUE")]
    rows = [payment("bad" + str(index), attempt_no=index + 1, status="FAILED", failure_code=code)
            for index, (code, _) in enumerate(cases)]
    rows += [payment("00000000-4000-8000-0000-000000000024", attempt_no=20, status="FAILED", failure_code="PG_ERROR"),
             payment("00000000-4000-8000-0000-000000000025", attempt_no=21, status="SUCCESS", failure_code="PG_ERROR"),
             payment("00000000-4000-8000-0000-000000000026", attempt_no=22)]
    result = build_silver([order()], [], rows)
    errors = {row["record_key"]: row for row in result["quarantined_records"]}
    for index, (_, expected) in enumerate(cases):
        assert errors[fixture_id("bad" + str(index))]["error_code"] == expected
    assert errors["00000000-4000-8000-0000-000000000025"]["error_code"] == "INVALID_VALUE"
    assert {row["payment_id"] for row in result["payment_attempts"]} == {"00000000-4000-8000-0000-000000000024", "00000000-4000-8000-0000-000000000026"}


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
        "items": [{"order_item_id": "00000000-4000-8000-0000-000000000004", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "0001",
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
    item = {"order_item_id": "00000000-4000-8000-0000-000000000004", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "0001",
            "quantity": 2, "unit_price": 500}
    unchecked = build_silver([order(total_amount=1200)], [item], [], input_complete=False)
    assert summary(unchecked, "orders")["amount_checks"][0]["status"] == "UNVERIFIED"
    assert not unchecked["quarantined_records"]
    passed = build_silver([order()], [item, dict(item)], [payment()], input_complete=True)
    assert summary(passed, "orders")["amount_checks"][0]["item_total_amount"] == 1000
    assert summary(passed, "orders")["amount_checks"][0]["status"] == "PASS"
    assert len(passed["orders_current"]) == 1
    result = build_silver([order(total_amount=1200), order("00000000-4000-8000-0000-00000000000a")],
                         [item, {**item, "order_item_id": "00000000-4000-8000-0000-000000000005", "order_id": "00000000-4000-8000-0000-00000000000a"}],
                         [payment(amount=1200), payment("00000000-4000-8000-0000-00000000001c", order_id="00000000-4000-8000-0000-00000000000a")], input_complete=True)
    assert [row["order_id"] for row in result["orders_current"]] == ["00000000-4000-8000-0000-00000000000a"]
    assert [row["order_id"] for row in result["order_status_history"]] == ["00000000-4000-8000-0000-00000000000a"]
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["00000000-4000-8000-0000-00000000001c"]
    issue = next(row for row in result["quarantined_records"] if row["error_code"] == "ORDER_TOTAL_MISMATCH")
    assert (issue["order_total_amount"], issue["item_total_amount"], issue["amount_difference"]) == (1200, 1000, -200)


def test_missing_or_invalid_items_do_not_become_zero_or_partial_sum_mismatches():
    missing = build_silver([order()], [], [payment()], input_complete=True)
    assert not missing["orders_current"] and not missing["payment_attempts"]
    assert summary(missing, "orders")["amount_checks"][0]["status"] == "PENDING_REFERENCE"
    assert all(row["error_code"] != "ORDER_TOTAL_MISMATCH" for row in missing["quarantined_records"])
    item = {"order_item_id": "00000000-4000-8000-0000-000000000004", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "0001",
            "quantity": 1, "unit_price": 500}
    broken = build_silver([order()], [item, {**item, "order_item_id": "00000000-4000-8000-0000-000000000005", "unit_price": 0}],
                          [payment()], input_complete=True)
    check = summary(broken, "orders")["amount_checks"][0]
    assert check["status"] == "ITEM_ERROR" and "item_total_amount" not in check
    assert not broken["orders_current"]


def test_bad_payment_does_not_stop_normal_orders_and_reexecution():
    orders = [order(), order("00000000-4000-8000-0000-00000000000a")]
    payments = [
        payment(),
        payment("00000000-4000-8000-0000-000000000012", order_id="00000000-4000-8000-0000-00000000000a", status="FAILED"),  # 필수 실패 코드 없음
    ]
    result = build_silver(orders, [], payments)
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["00000000-4000-8000-0000-000000000011"]
    assert len(result["orders_current"]) == 2
    issue = result["quarantined_records"][0]
    assert (issue["record_key"], issue["field"], issue["error_code"]) == (
        "00000000-4000-8000-0000-000000000012", "failure_code", "MISSING_FIELD",
    )
    quality = summary(result, "payments")
    assert (quality["input_count"], quality["accepted_count"], quality["quarantined_count"]) == (2, 1, 1)
    assert quality["status"] == "INCOMPLETE"
    assert quality["affected_order_ids"] == ["00000000-4000-8000-0000-00000000000a"]
    assert result == build_silver(deepcopy(orders), [], deepcopy(payments))
    assert "raw_data" not in issue


def test_duplicate_conflict_retry_and_invalid_duplicate_are_distinct():
    first = payment()
    clash = payment("00000000-4000-8000-0000-000000000016", order_id="00000000-4000-8000-0000-00000000000a", status="FAILED", failure_code="PG_TIMEOUT")
    invalid = payment("00000000-4000-8000-0000-000000000017", order_id="00000000-4000-8000-0000-00000000000b")
    result = build_silver(
        [order(), order("00000000-4000-8000-0000-00000000000a"), order("00000000-4000-8000-0000-00000000000b")], [],
        [first, dict(first),
         payment("00000000-4000-8000-0000-000000000019", status="FAILED", failure_code="PG_ERROR", attempt_no=2),
         clash, {**clash, "failure_code": "PG_ERROR"},
         invalid, {**invalid, "status": "FAILED"}],
    )
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["00000000-4000-8000-0000-000000000011", "00000000-4000-8000-0000-000000000019"]
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
        [], [payment(), payment("00000000-4000-8000-0000-000000000018", order_id="00000000-4000-8000-0000-00000000000d")],
    )
    assert result["orders_current"] == []
    assert result["order_status_history"] == []
    assert result["payment_attempts"] == []
    issues = {row["record_key"]: row for row in result["quarantined_records"] if row["source_dataset"] == "payments"}
    assert issues["00000000-4000-8000-0000-000000000011"]["category"] == "DEPENDENCY_BLOCKED"
    assert issues["00000000-4000-8000-0000-000000000018"]["category"] == "PENDING_REFERENCE"


def test_retry_sequence_and_amount_failures_do_not_remove_unrelated_success():
    result = build_silver(
        [order(), order("00000000-4000-8000-0000-00000000000a"), order("00000000-4000-8000-0000-00000000000b"), order("00000000-4000-8000-0000-00000000000c")], [],
        [payment(), payment("00000000-4000-8000-0000-000000000013", order_id="00000000-4000-8000-0000-00000000000a"), payment("00000000-4000-8000-0000-000000000015", order_id="00000000-4000-8000-0000-00000000000a"),
         payment("00000000-4000-8000-0000-000000000014", order_id="00000000-4000-8000-0000-00000000000b", amount=500),
         payment("00000000-4000-8000-0000-00000000001a", order_id="00000000-4000-8000-0000-00000000000c"), payment("00000000-4000-8000-0000-00000000001b", order_id="00000000-4000-8000-0000-00000000000c", attempt_no=2)],
    )
    assert [row["payment_id"] for row in result["payment_attempts"]] == ["00000000-4000-8000-0000-000000000011"]
    codes = {row["error_code"] for row in result["quarantined_records"]}
    assert codes == {"ATTEMPT_CONFLICT", "AMOUNT_MISMATCH", "MULTIPLE_SUCCESSES"}


def test_history_item_totals_and_invalid_shapes():
    item = {"order_item_id": "00000000-4000-8000-0000-000000000001", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "A-1", "quantity": 2, "unit_price": 500}
    result = build_silver(
        [order(), order(status="PAID", updated_at="2026-10-14T00:02:00+09:00")],
        [item, dict(item), {**item, "order_item_id": "00000000-4000-8000-0000-000000000003", "unit_price": 0}],
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
        if name == "order_amount_checks":
            continue  # 실행 ID·검사 시각은 재실행마다 바뀌며 업무 판정값은 별도 검증한다.
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


def test_r6_output_fixed_evidence_recheck_and_failed_manifest(tmp_path, monkeypatch):
    from datetime import datetime

    source = tmp_path / "input"
    source.mkdir()
    locations = [source / (name + ".jsonl") for name in ("orders", "items", "payments")]
    item = {"order_item_id": fixture_id("r6-item"), "order_id": order()["order_id"],
            "article_id": "0001", "quantity": 2, "unit_price": 5900}
    output = tmp_path / "output"

    def execute(total=12800, complete=True, items=None):
        values = ([order(total_amount=total)], [item] if items is None else items,
                  [payment(amount=total)])
        for path, rows in zip(locations, values, strict=True):
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return run(*(str(path) for path in locations), str(output), input_complete=complete)

    def check_row(manifest):
        rows = [json.loads(line) for line in Path(manifest["outputs"]["order_amount_checks"])
                .read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        row = rows[0]
        assert row["run_id"] == manifest["run_id"]
        assert row["checked_at"] == manifest["checked_at"]
        assert datetime.fromisoformat(row["checked_at"]).utcoffset().total_seconds() == 0
        assert row["check_name"] == "order_item_total_match"
        assert row["check_version"] == "items-sum-v1"
        assert row["source_manifest"] == manifest["fixed_manifest_path"]
        assert json.loads(Path(row["source_manifest"]).read_text(encoding="utf-8")) == manifest
        return row

    first = execute()
    fixed = Path(first["fixed_manifest_path"])
    evidence = fixed.read_bytes()
    first_row = check_row(first)
    assert (first_row["status"], first_row["amount_difference"]) == ("MISMATCH", -1000)
    second = execute()
    second_row = check_row(second)
    assert second_row["run_id"] != first_row["run_id"]
    assert second_row["status"] == "MISMATCH"
    third = execute(11800)
    assert (check_row(third)["status"], check_row(third)["amount_difference"]) == ("PASS", 0)
    assert fixed.read_bytes() == evidence  # 최신 참조가 바뀌어도 과거 근거는 그대로다.
    for manifest, expected in ((execute(complete=False), "UNVERIFIED"),
                               (execute(items=[]), "PENDING_REFERENCE"),
                               (execute(items=[{**item, "unit_price": 0}]), "ITEM_ERROR")):
        row = check_row(manifest)
        assert row["status"] == expected
        assert row["item_total_amount"] is None and row["amount_difference"] is None

    current = Path(first["manifest_path"])
    before = current.read_bytes()
    runs_before = set(current.parent.joinpath("runs").iterdir())
    original = Path.write_text

    def fail_fixed(path, *args, **kwargs):
        if path.name == "manifest.json":
            raise OSError("fixed manifest write failed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_fixed)
    with pytest.raises(OSError, match="fixed manifest"):
        execute()
    assert current.read_bytes() == before
    assert set(current.parent.joinpath("runs").iterdir()) == runs_before
