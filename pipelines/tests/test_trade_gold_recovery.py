from copy import deepcopy

import pytest

from pipelines.trade_gold_recovery import (
    bounded_holds,
    digest,
    policy_keys,
    validate_publication,
    validate_source,
)

ID = "00000000-0000-4000-8000-000000000001"


def policy():
    return {"version": 1, "approval": "exclude-confirmed-synthetic-tests-only", "source_run_id": "base",
            "records": [{"dataset": "payments", "key": ID, "evidence": "confirmed-test-1"}],
            "expected_excluded_active_errors": 1}


def issue(**fields):
    return {"order_id": "order-1", "error_code": "MISSING_ORDER_ITEMS", "active": True, **fields}


def candidate(**fields):
    return {"order_id": "order-1", "source_dataset": "orders", "valid": True,
            "ordered_at": "2026-10-20T08:39:15.432897Z", **fields}


def test_exact_test_policy_does_not_expand_to_other_record_types():
    keys = policy_keys(policy())
    assert keys == {"payments": {ID}, "orders": set(), "order_items": set()}


@pytest.mark.parametrize("change", [
    {"approval": "exclude-all-errors"}, {"version": 2}, {"unknown": True},
    {"records": []}, {"records": [{"dataset": "payments", "key": "*", "evidence": "test"}]},
    {"records": [{"dataset": "other", "key": ID, "evidence": "test"}]},
    {"records": [{"dataset": "payments", "key": ID, "evidence": ""}]},
])
def test_invalid_exclusion_policy_is_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        policy_keys({**policy(), **change})


def test_duplicate_exclusion_rejected():
    p = policy()
    p["records"] *= 2
    with pytest.raises(ValueError):
        policy_keys(p)


def test_missing_item_holds_known_hour_and_whole_product_date():
    holds, affected = bounded_holds([issue()], [candidate()])
    assert affected == {"order-1"}
    assert [r["key"] for r in holds] == [
        {"hour_start_kst": "2026-10-20T17:00:00+09:00"}, {"sales_date_kst": "2026-10-20"}]
    assert all(r["key"] for r in holds)


def test_payment_date_is_also_protected_across_midnight():
    holds, _ = bounded_holds([issue()], [candidate(), candidate(source_dataset="payments", completed_at="2026-10-21T16:00:00Z")])
    assert {r["key"]["sales_date_kst"] for r in holds if r["table"] == "product_sales_daily"} == {"2026-10-20", "2026-10-22"}


@pytest.mark.parametrize("rows,errors", [
    ([], [issue()]), ([candidate(valid=False)], [issue()]),
    ([candidate(ordered_at=None)], [issue()]), ([candidate(ordered_at="2026-10-20T01:00:00")], [issue()]),
    ([candidate()], [issue(order_id=None)]), ([candidate()], [issue(error_code="OTHER")]),
])
def test_unknown_scope_retains_whole_table_hold(rows, errors):
    holds, _ = bounded_holds(errors, rows)
    assert len(holds) == 2 and all(r["key"] == {} for r in holds)


def test_inactive_errors_do_not_carry_a_stale_hold():
    assert bounded_holds([issue(active=False)], []) == ([], set())


def test_context_overflow_is_not_silently_truncated():
    holds, _ = bounded_holds([issue()], [candidate()] * 1001)
    assert all(r["reason"] == "SCOPE_METADATA_LIMIT" and not r["key"] for r in holds)


def test_recovery_requires_same_immutable_silver_as_previous_gold():
    s = {"run_id": "base", "engine": "spark", "status": "INCOMPLETE", "input_completeness": "DECLARED_COMPLETE"}
    previous = {"status": "PARTIAL", "silver_manifest": "s3://lake/silver/runtime/trade/runs/base/manifest.json"}
    assert validate_source(s, previous, policy(), "s3://lake") == previous["silver_manifest"]
    for key, value in [("engine", "python"), ("status", "FAILED"), ("input_completeness", "UNKNOWN")]:
        bad = deepcopy(s)
        bad[key] = value
        with pytest.raises(ValueError):
            validate_source(bad, previous, policy(), "s3://lake")
    with pytest.raises(ValueError):
        validate_source(s, {**previous, "silver_manifest": "s3://lake/other"}, policy(), "s3://lake")


@pytest.mark.parametrize("failure", [None, "source-hash", "policy-hash", "excluded-count", "policy-prefix", "source-done"])
def test_publication_verifies_source_policy_and_exclusion_evidence(failure):
    import json
    from types import SimpleNamespace

    source = json.dumps({"run_id": "base"}).encode()
    raw_policy = json.dumps(policy()).encode()
    source_key = "silver/runtime/trade/runs/base/manifest.json"
    policy_key = "pipelines/requests/trade-recovery/policy.json"
    objects = {source_key: source, "silver/runtime/trade/completed/base.json": source, policy_key: raw_policy}
    store = SimpleNamespace(uri=lambda k: "s3://lake/" + k, get=lambda k: (objects.get(k), None))
    m = {"silver_run_id": "base", "silver_manifest": store.uri(source_key), "silver_manifest_sha256": digest(source),
         "trade_recovery": {"policy_uri": store.uri(policy_key), "policy_sha256": digest(raw_policy), "excluded_active_error_count": 1}}
    if failure == "source-hash": m["silver_manifest_sha256"] = "bad"
    if failure == "policy-hash": m["trade_recovery"]["policy_sha256"] = "bad"
    if failure == "excluded-count": m["trade_recovery"]["excluded_active_error_count"] = 2
    if failure == "policy-prefix": m["trade_recovery"]["policy_uri"] = "s3://lake/other.json"
    if failure == "source-done": objects["silver/runtime/trade/completed/base.json"] = b'{}'
    if failure:
        with pytest.raises(ValueError): validate_publication(store, m)
    else:
        validate_publication(store, m)
