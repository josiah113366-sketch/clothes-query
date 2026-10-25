"""Bounded planning, source identity, checkpoint and query failure gates."""
import hashlib
import json
from unittest.mock import Mock

import pytest

from pipelines.funnel_control import (
    CONTROL,
    LocalStore,
    acquire,
    advance,
    release,
    verify_athena,
)
from pipelines.funnel_demo import encode
from pipelines.funnel_incremental import identity, normalize_partition, plan_batch


def item(day, name, size=10):
    return {"uri": f"s3://bucket/bronze_v2/clickstream/year=2026/month=10/day={day}/{name}.json",
            "etag": '"fixed"', "size": size}


def test_backfill_orders_arrival_dates_without_splitting_cohort_and_honors_limits():
    files = [item("22", "z"), item("21", "c"), item("21", "b"), item("21", "a")]
    first = plan_batch(files, max_files=2, max_bytes=25)
    assert [row["uri"].rsplit("/", 1)[1] for row in first["objects"]] == ["a.json", "b.json"]
    assert first["remaining_files"] == 2
    second = plan_batch(files, [identity(row) for row in first["objects"]])
    assert second["ingestion_date_utc"] == "2026-10-21"
    assert len(second["objects"]) == 1
    assert plan_batch(files, [identity(row) for row in files])["objects"] == []


@pytest.mark.parametrize("change", ["mutate", "delete", "duplicate", "oversize"])
def test_never_skips_changed_missing_duplicate_or_oversize_input(change):
    original = item("21", "a")
    files = [dict(original)]
    processed = [identity(original)]
    if change == "mutate":
        files[0]["etag"] = '"changed"'
    elif change == "delete":
        files = []
    elif change == "duplicate":
        files *= 2
    else:
        files = [item("21", "big", 100)]
        processed = []
    with pytest.raises(ValueError):
        plan_batch(files, processed, max_bytes=50)


def test_checkpoint_blocks_stale_and_concurrent_execution_and_advances_only_verified_run(tmp_path):
    store = LocalStore(tmp_path)
    config = {"run_id": "one", "previous": None}
    acquire(store, config)
    with pytest.raises(ValueError):
        acquire(store, {"run_id": "two", "previous": None})
    release(store, "one")
    assert json.loads(store.get(CONTROL)[0])["tip"] is None
    acquire(store, config)
    digest = hashlib.sha256(b"manifest").hexdigest()
    advance(store, config, "fixed.json", digest, "query-success")
    advance(store, config, "fixed.json", digest, "query-success")
    with pytest.raises(ValueError):
        acquire(store, {"run_id": "two", "previous": None})
    value = json.loads(store.get(CONTROL)[0])
    assert value["tip"] == {"uri": "fixed.json", "sha256": digest}
    assert value["athena_query_id"] == "query-success"


def athena(rows=None, status="SUCCEEDED"):
    client = Mock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": status}}}
    client.get_query_results.return_value = {"ResultSet": {"Rows": [{"Data": []}] + [
        {"Data": [{"VarCharValue": name}, {"VarCharValue": str(count)}]} for name, count in (rows or {}).items()]}}
    return client


def test_athena_verifies_all_metrics_and_holds_with_same_run():
    counts = {"funnel_session_product": 3, "funnel_daily": 2, "refresh_holds": 0}
    client = athena(counts)
    assert verify_athena(client, "gold_a", "pipeline", "s3://bucket/results/", "run1", counts) == "q"
    sql = client.start_query_execution.call_args.kwargs["QueryString"]
    assert sql.count("run_id = 'run1'") == 3
    assert "channel = 'funnels'" in sql


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "WRONG_COUNTS"])
def test_failed_or_inconsistent_query_cannot_pass(status):
    client = athena({"funnel_session_product": 99}, status if status != "WRONG_COUNTS" else "SUCCEEDED")
    with pytest.raises((ValueError, RuntimeError)):
        verify_athena(client, "gold_a", "pipeline", "s3://bucket/results/", "run1", {
            "funnel_session_product": 3, "funnel_daily": 2, "refresh_holds": 0})


def test_invalid_json_is_retained_as_global_quality_hold_without_raw_payload():
    rows = list(normalize_partition([("s3://bucket/source", '{bad-json\n')]))
    assert len(rows) == 1
    assert rows[0][2] is None
    assert rows[0][3] is None
    assert rows[0][4] == "PARSE_ERROR"
    assert "bad-json" not in encode(rows).decode()


def test_backfill_partitions_are_queryable_without_replacing_dashboard_registry():
    from pipelines.gold_publication import GoldPublisher
    from pipelines.tests.test_r6_publication import MemoryStore
    store = MemoryStore()
    base = "gold_a/runtime/funnels/runs/backfill"
    names = ("funnel_session_product", "funnel_daily", "refresh_holds")
    manifest = {"run_id": "backfill", "status": "PARTIAL", "output_counts": {name: 1 for name in names},
                "outputs": {name: store.uri(base + "/" + name) for name in names},
                "schemas": {name: {"fields": [{"name": "test", "type": "string"}]} for name in names}}
    for name in names:
        store.data[base + "/" + name + "/part.parquet"] = b"not read by publisher"
    store.data[base + "/manifest.json"] = encode(manifest)
    store.data["gold_a/runtime/funnels/completed/backfill.json"] = encode(manifest)
    publisher = GoldPublisher(store, Mock(), "gold_a", "funnels")
    publisher.table = Mock(return_value={})
    publisher.register = Mock()
    assert publisher.publish("backfill", advertise=False)["status"] == "STAGED"
    assert publisher.register.call_count == 3
    assert not any(key.startswith("gold_a/runtime/funnels/catalog/completed/") for key in store.data)
