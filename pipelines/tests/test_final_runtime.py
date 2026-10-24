"""조회 고정·재처리 인계·완료 공개의 실패 경계를 검증한다. AWS 호출은 가짜 클라이언트다."""
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pipelines.gold_publication import RUN_COLUMNS, GoldPublisher
from pipelines.r6_publication import PublicationError, encode
from pipelines.reprocess import prepare, record_result, validate_request
from pipelines.review_scores import snapshot_scores
from pipelines.runtime_control import trade_lease
from pipelines.tests.test_r6_publication import MemoryStore, read


class Missing(Exception):
    pass


class S3:
    exceptions = SimpleNamespace(NoSuchKey=Missing)

    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        body = self.objects.get((Bucket, Key))
        if body is None:
            raise Missing()
        return {"Body": io.BytesIO(body), "ETag": hashlib.sha256(body).hexdigest()}

    def put_object(self, Bucket, Key, Body, **conditions):
        old = self.objects.get((Bucket, Key))
        if "IfNoneMatch" in conditions and old is not None:
            raise AssertionError("immutable object replaced")
        if "IfMatch" in conditions:
            assert conditions["IfMatch"] == hashlib.sha256(old).hexdigest()
        self.objects[Bucket, Key] = Body
        return {"ETag": hashlib.sha256(Body).hexdigest()}

    def head_object(self, Bucket, Key):
        body = self.objects[Bucket, Key]
        return {"ETag": hashlib.sha256(body).hexdigest(), "ContentLength": len(body)}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return SimpleNamespace(paginate=lambda Bucket, Prefix: [{"Contents": [
            {"Key": k, "ETag": hashlib.sha256(v).hexdigest(), "Size": len(v)}
            for (b, k), v in self.objects.items() if b == Bucket and k.startswith(Prefix)]}])


class Athena:
    def __init__(self, s3, state="SUCCEEDED", empty=False):
        self.s3, self.state, self.empty, self.calls = s3, state, empty, []

    def start_query_execution(self, **kwargs):
        self.calls.append(kwargs)
        self.prefix = re.search(r" TO '(s3://[^']+)'", kwargs["QueryString"])[1]
        self.uri = self.prefix + "fixed.parquet"
        if not self.empty:
            self.s3.objects["bucket", self.uri.removeprefix("s3://bucket/")] = b"fixed query output"
        return {"QueryExecutionId": "query-1"}

    def get_query_execution(self, **kwargs):
        return {"QueryExecution": {"Status": {"State": self.state}}}

    def get_paginator(self, name):
        assert name == "get_query_results"
        def pages(**kwargs):
            assert kwargs["QueryResultType"] == "DATA_MANIFEST"
            return [{"ResultSet": {"Rows": [] if self.empty else [{"Data": [{"VarCharValue": self.uri}]}]}}]
        return SimpleNamespace(paginate=pages)


def test_review_latest_query_is_pinned_and_not_requeried_on_retry():
    s3 = S3()
    athena = Athena(s3)
    args = ("s3://bucket", "reviews-1", "2026-10-21", "2026-10-22", {"workgroup": "review-gold"}, athena, s3)
    first = snapshot_scores(*args)
    assert snapshot_scores(*args) == first
    assert len(athena.calls) == 1
    assert "review_aspect_scores_latest" in athena.calls[0]["QueryString"]
    assert "format = 'PARQUET'" in athena.calls[0]["QueryString"]
    assert first["query_execution_id"] == "query-1"
    assert "iceberg_snapshot_id" not in first
    assert first["objects"][0]["etag"]


def test_review_empty_and_failed_queries_are_distinct():
    for state, empty in (("SUCCEEDED", True), ("FAILED", False)):
        s3 = S3()
        athena = Athena(s3, state, empty)
        args = ("s3://bucket", "reviews-1", "2026-10-21", "2026-10-21", {"workgroup": "wg"}, athena, s3)
        if state == "FAILED":
            with pytest.raises(RuntimeError):
                snapshot_scores(*args)
            assert not any(k.endswith("manifest.json") for _, k in s3.objects)
        else:
            assert snapshot_scores(*args)["objects"] == []


def request():
    return {"request_id": "req-1", "window_start": "2026-10-21 00:00:00", "window_end": "2026-10-21 01:00:00",
            "rule_version": "0.2.0", "order_ids": ["order-1"], "source": "SILVER", "attempt": 1}


def test_reprocess_prepare_fixes_objects_and_requires_completed_baseline():
    s3 = S3()
    runtime = {"output_root": "s3://bucket", "inputs": {name: ["s3://bucket/" + prefix + "/"] for name, prefix in (
        ("orders", "bronze_v2/orders"), ("order_items", "bronze_v2/order-items"), ("payments", "bronze_v2/payments"),
        ("designs", "seed/designs"), ("variants", "seed/variants"))}}
    for paths in runtime["inputs"].values():
        s3.objects["bucket", paths[0].removeprefix("s3://bucket/") + "part.jsonl"] = b"{}\n"
    with pytest.raises(Missing):
        prepare(request(), runtime, s3)
    uri = "s3://bucket/silver/runtime/trade/runs/base/manifest.json"
    previous = {"run_id": "base", "outputs": {"dq_order_results": "placeholder"}}
    for key in ("silver/runtime/trade/current.json", uri.removeprefix("s3://bucket/")):
        s3.objects["bucket", key] = encode(previous)
    s3.objects["bucket", "gold_a/runtime/trade/current.json"] = encode({"run_id": "base", "silver_manifest": uri})
    prepared = prepare(request(), runtime, s3)
    assert prepared == prepare(request(), runtime, s3)
    config = json.loads(s3.objects["bucket", prepared.removeprefix("s3://bucket/")])
    assert config["reprocess_scope"]["order_ids"] == ["order-1"]
    assert all(not uri.endswith("/") for paths in config["inputs"].values() for uri in paths)
    with pytest.raises(ValueError, match="이미 고정"):
        prepare({**request(), "order_ids": ["other"]}, runtime, s3)


def test_reprocess_rejects_invalid_scope_and_records_partial_without_verifying():
    with pytest.raises(ValueError):
        validate_request({**request(), "order_ids": ["o"] * 501})
    s3 = S3()
    run = "reprocess-req-1-1"
    s3.objects["bucket", f"silver/runtime/trade/completed/{run}.json"] = encode({"run_id": run, "actual_scope": {"order_ids": ["order-1"]}})
    s3.objects["bucket", f"gold_a/runtime/trade/completed/{run}.json"] = encode({"run_id": run, "held_scopes": [{"table": "order_sales_hourly"}]})
    for layer in ("silver", "gold_a"):
        s3.objects["bucket", f"{layer}/runtime/trade/catalog/completed/{run}.parquet"] = b"published"
    detail = record_result(request(), "s3://bucket", s3)
    assert detail["status"] == "PARTIAL"
    event = read(next(v for (_, key), v in s3.objects.items() if key.startswith("gold_b/reprocess_events/")))[0]
    assert event["source"] == "SILVER" and event["step"] == "LEDGER_REPLACED"
    assert event["window_start"] == datetime(2026, 10, 21)
    # R6 PASS/VERIFIED와 원본 DB 복구는 이 잡이 대신하지 않는다.
    assert "VERIFIED" not in event.values()


def test_large_successful_scope_reference_does_not_invent_holds():
    s3 = S3()
    run = "reprocess-req-1-1"
    scope = {"order_ids": ["00000000-0000-0000-0000-" + str(i).zfill(12) for i in range(500)]}
    s3.objects["bucket", f"silver/runtime/trade/completed/{run}.json"] = encode({"run_id": run, "actual_scope": scope})
    s3.objects["bucket", f"gold_a/runtime/trade/completed/{run}.json"] = encode({"run_id": run, "held_scopes": []})
    for layer in ("silver", "gold_a"):
        s3.objects["bucket", f"{layer}/runtime/trade/catalog/completed/{run}.parquet"] = b"published"
    detail = record_result(request(), "s3://bucket", s3)
    assert detail["status"] == "SUCCESS" and detail["held_scopes"] == []
    assert "manifest_ref" in detail["actual_scope"]
    assert len(encode(detail)) < 16000


class Glue:
    exceptions = SimpleNamespace(EntityNotFoundException=Missing, AlreadyExistsException=RuntimeError)

    def __init__(self, store):
        self.partitions, self.tables, self.fail = {}, {}, False
        definitions = {"gold_runs": (RUN_COLUMNS, [("channel", "string")], "gold_a/catalog/"),
                       "order_sales_hourly_runs": ([("hour_start_kst", "string")], [("run_id", "string")], "gold_a/runtime/trade/runs/"),
                       "product_sales_daily_runs": ([("sales_date_kst", "string")], [("run_id", "string")], "gold_a/runtime/trade/runs/"),
                       "refresh_holds_runs": ([("reason", "string")], [("channel", "string"), ("run_id", "string")], "gold_a/catalog/holds/")}
        for name, (columns, keys, prefix) in definitions.items():
            self.tables[name] = {"StorageDescriptor": {"Columns": [{"Name": n, "Type": t} for n, t in columns],
                "Location": store.uri(prefix), "InputFormat": "parquet"}, "PartitionKeys": [{"Name": n, "Type": t} for n, t in keys]}

    def get_table(self, DatabaseName, Name):
        return {"Table": self.tables[Name]}

    def get_partition(self, DatabaseName, TableName, PartitionValues):
        key = TableName, tuple(PartitionValues)
        if key not in self.partitions:
            raise Missing()
        return {"Partition": self.partitions[key]}

    def create_partition(self, DatabaseName, TableName, PartitionInput):
        if self.fail:
            raise OSError("temporary Glue failure")
        self.partitions[TableName, tuple(PartitionInput["Values"])] = PartitionInput


def add_gold(store, run):
    base = f"gold_a/runtime/trade/runs/{run}"
    schemas = {"order_sales_hourly": {"fields": [{"name": "hour_start_kst", "type": "string"}]},
               "product_sales_daily": {"fields": [{"name": "sales_date_kst", "type": "string"}]},
               "refresh_holds": {"fields": [{"name": "reason", "type": "string"}]}}
    manifest = {"run_id": run, "status": "PARTIAL", "held_scopes": [{"table": "order_sales_hourly"}],
                "outputs": {name: store.uri(base + "/" + name) for name in schemas}, "schemas": schemas,
                "output_counts": {name: 0 for name in schemas}, "code_ref": "test"}
    store.data[base + "/manifest.json"] = encode(manifest)
    store.data[f"gold_a/runtime/trade/completed/{run}.json"] = encode(manifest)
    for name in schemas:
        store.data[base + "/" + name + "/part-0.parquet"] = b"Parquet presence checked separately by Spark"


def test_gold_failed_registration_is_not_completed_and_retry_is_ordered():
    store = MemoryStore()
    glue = Glue(store)
    add_gold(store, "run-1")
    publisher = GoldPublisher(store, glue, "gold_a", "trade", clock=lambda: datetime(2026, 10, 21, tzinfo=timezone.utc))
    glue.fail = True
    with pytest.raises(OSError):
        publisher.publish("run-1")
    assert not any(k.startswith("gold_a/runtime/trade/catalog/completed/") for k in store.data)
    glue.fail = False
    first = publisher.publish("run-1")
    assert publisher.publish("run-1")["completed_at"] == first["completed_at"]
    add_gold(store, "run-2")
    second = publisher.publish("run-2")
    assert second["completed_at"] > first["completed_at"]
    published = read(store.data["gold_a/runtime/trade/catalog/completed/run-2.parquet"])[0]
    assert published["quality_status"] == "PARTIAL" and published["held_scope_count"] == 1
    assert ("refresh_holds_runs", ("trade", "run-2")) in glue.partitions
    glue.tables["gold_runs"]["StorageDescriptor"]["Location"] = "s3://wrong/"
    with pytest.raises(PublicationError):
        publisher.publish("run-2")


def test_trade_workflows_cannot_overlap_and_failed_process_releases_lease():
    s3 = S3()
    with pytest.raises(ValueError, match="processing failure"), trade_lease("s3://bucket", s3):
        with pytest.raises(RuntimeError), trade_lease("s3://bucket", s3):
            pytest.fail("overlapping writer acquired lease")
        raise ValueError("processing failure")
    key = "bucket", "silver/runtime/trade/control/processing.json"
    assert json.loads(s3.objects[key])["owner"] is None
    s3.objects[key] = encode({"owner": "stopped-process"})
    with pytest.raises(RuntimeError), trade_lease("s3://bucket", s3, "wrong-owner"):
        pytest.fail("incorrect recovery owner")
    assert json.loads(s3.objects[key])["owner"] == "stopped-process"
    with trade_lease("s3://bucket", s3, "stopped-process"):
        assert json.loads(s3.objects[key])["owner"] != "stopped-process"
    assert json.loads(s3.objects[key])["owner"] is None
