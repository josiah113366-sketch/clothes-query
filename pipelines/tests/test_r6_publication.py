"""공개 순서·재시도·정밀도·완료 목록 노출을 실제 Parquet과 가짜 S3/Glue로 검증한다."""
import copy
import hashlib
import io
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.r6_publication import (
    CHECK_COLUMNS,
    RUN_COLUMNS,
    GlueCatalog,
    PublicationError,
    Publisher,
    S3Store,
    encode,
    parquet,
    schema,
)

UTC = timezone.utc


class MemoryStore:
    root = "s3://test-bucket"

    def __init__(self):
        self.data = {}
        self.fail_after_registry = False

    def uri(self, name):
        return self.root + "/" + name

    def get(self, name):
        body = self.data.get(name)
        return body, hashlib.sha256(body).hexdigest() if body is not None else None

    def put(self, name, body, etag=None):
        old, current = self.get(name)
        if (etag and current != etag) or (not etag and old is not None):
            raise PublicationError("conditional conflict")
        if (self.fail_after_registry and name == Publisher.STATE and json.loads(body).get("owner") is None
                and any(k.startswith("silver/runtime/trade/catalog/completed/") for k in self.data)):
            self.fail_after_registry = False
            raise OSError("simulated process/storage interruption")
        self.data[name] = body
        return hashlib.sha256(body).hexdigest()

    immutable = S3Store.immutable

    def files(self, prefix):
        return sorted(k for k in self.data if k.startswith(prefix) and k.endswith(".parquet"))


class Catalog:
    def __init__(self):
        self.partitions = {}
        self.fail_once = False

    def validate(self):
        pass

    def register(self, run, location, digest):
        if self.fail_once:
            self.fail_once = False
            raise OSError("simulated registration failure")
        previous = self.partitions.setdefault(run, (location, digest))
        if previous != (location, digest):
            raise PublicationError("immutable partition mismatch")


def read(body):
    return pq.ParquetFile(io.BytesIO(body)).read().to_pylist()


def add_run(store, run="run-1", status="PASS", micros=123456):
    at = datetime(2026, 10, 23, 15, 59, 59, micros, tzinfo=UTC)
    base = "silver/runtime/trade/runs/" + run + "/"
    columns = [(k, v) for k, v in CHECK_COLUMNS if k not in {"checked_at_utc", "format_rule_version"}]
    original_schema = pa.schema([(n, pa.timestamp("us", tz="UTC") if n == "checked_at" else schema([(n, t)])[0].type)
                                 for n, t in columns] + [("run_id", pa.string())])
    row = {"order_id": "order-1", "check_name": "order_item_total_match", "check_version": "items-sum-v1",
           "status": status, "order_total_amount": 21800 if status == "MISMATCH" else 11800,
           "item_total_amount": 11800, "amount_difference": -10000 if status == "MISMATCH" else 0,
           "checked_at": at, "source_manifest": store.uri(base + "manifest.json"), "run_id": run}
    stream = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([row], schema=original_schema), stream)
    store.data[base + "order_amount_checks/part-00000.parquet"] = stream.getvalue()
    manifest = {"run_id": run, "status": "PASS" if status == "PASS" else "INCOMPLETE",
                "checked_at": at.isoformat(), "check_version": "transactions.v8",
                "format_rules": {"version": "0.2.0"}, "coverage_status": "UNVERIFIED", "code_ref": "abc123",
                "outputs": {"order_amount_checks": store.uri(base + "order_amount_checks")},
                "output_counts": {"order_amount_checks": 1}}
    save_manifest(store, manifest)
    return manifest


def save_manifest(store, manifest):
    run = manifest["run_id"]
    store.data["silver/runtime/trade/runs/" + run + "/manifest.json"] = encode(manifest)
    store.data["silver/runtime/trade/completed/" + run + ".json"] = encode(manifest)


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.store, self.catalog = MemoryStore(), Catalog()
        self.now = datetime(2026, 10, 24, 1, 0, 0, 999999, tzinfo=UTC)
        self.publisher = Publisher(self.store, self.catalog, lambda: self.now)
        add_run(self.store)

    def registry(self, run="run-1"):
        return self.store.get("silver/runtime/trade/catalog/completed/" + run + ".parquet")[0]

    def test_projection_preserves_exact_time_and_source_without_rounding(self):
        source = copy.deepcopy(self.store.data)
        result = self.publisher.publish("run-1")
        self.assertEqual(result["status"], "COMPLETED")
        body = self.store.get("silver/runtime/trade/catalog-data/runs/run-1/order_amount_checks/part-00000.parquet")[0]
        row = read(body)[0]
        self.assertEqual(row["checked_at"].microsecond, 123000)
        self.assertEqual(row["checked_at_utc"], "2026-10-23T15:59:59.123456Z")
        self.assertNotIn("run_id", row)  # Athena 파티션 컬럼과 중복하지 않는다.
        self.assertEqual(pq.ParquetFile(io.BytesIO(body)).schema_arrow.field("checked_at").type, pa.timestamp("ms"))
        self.assertEqual(row["amount_difference"], 0)
        for key, value in source.items():
            self.assertEqual(self.store.data[key], value)

    def test_all_check_states_are_published_without_becoming_pass(self):
        for i, status in enumerate(["MISMATCH", "UNVERIFIED", "PENDING_REFERENCE", "ITEM_ERROR", "PASS"]):
            run = "state-" + str(i)
            add_run(self.store, run, status, micros=999999)
            self.publisher.publish(run)
            record = read(self.registry(run))[0]
            self.assertEqual(record["status"], "COMPLETED")
            self.assertEqual(record["quality_status"], "PASS" if status == "PASS" else "INCOMPLETE")
            body = self.store.get("silver/runtime/trade/catalog-data/runs/" + run + "/order_amount_checks/part-00000.parquet")[0]
            row = read(body)[0]
            self.assertEqual(row["status"], status)
            self.assertEqual(row["checked_at"].second, 59)
            self.assertEqual(row["checked_at"].microsecond, 999000)
            if status == "MISMATCH":
                self.assertEqual(row["amount_difference"], -10000)

    def test_idempotent_retry_does_not_duplicate_or_change_completed_at(self):
        self.publisher.publish("run-1")
        original = copy.deepcopy(self.store.data)
        self.now += timedelta(days=1)
        self.assertEqual(self.publisher.publish("run-1")["status"], "ALREADY_PUBLISHED")
        self.assertEqual(self.store.data, original)

    def test_failed_partition_is_not_visible_and_blocks_later_publication(self):
        self.catalog.fail_once = True
        with self.assertRaises(OSError):
            self.publisher.publish("run-1")
        self.assertIsNone(self.registry())
        add_run(self.store, "run-2")
        with self.assertRaises(PublicationError):
            self.publisher.publish("run-2")
        self.publisher.publish("run-1")
        self.publisher.publish("run-2")
        self.assertIsNotNone(self.registry("run-2"))

    def test_clock_rollback_still_gives_strict_publication_order(self):
        self.publisher.publish("run-1")
        first = read(self.registry())[0]["completed_at"]
        self.now -= timedelta(days=1)
        add_run(self.store, "run-2")
        self.publisher.publish("run-2")
        second = read(self.registry("run-2"))[0]["completed_at"]
        self.assertEqual(second, first + timedelta(milliseconds=1))

    def test_interruption_after_registry_resumes_same_publication_once(self):
        self.store.fail_after_registry = True
        with self.assertRaises(OSError):
            self.publisher.publish("run-1")
        original = self.registry()
        state = json.loads(self.store.get(Publisher.STATE)[0])
        with self.assertRaises(PublicationError):
            self.publisher.publish("run-1")
        with self.assertRaises(PublicationError):
            self.publisher.recover("wrong-owner")
        self.publisher.recover(state["owner"])  # 이전 프로세스가 끝난 상황
        self.assertEqual(self.publisher.publish("run-1")["status"], "ALREADY_PUBLISHED")
        self.assertEqual(self.registry(), original)
        self.assertIsNone(json.loads(self.store.get(Publisher.STATE)[0])["pending_run_id"])

    def test_published_run_cannot_be_replaced_with_changed_source(self):
        self.publisher.publish("run-1")
        original = self.registry()
        manifest = json.loads(self.store.get("silver/runtime/trade/runs/run-1/manifest.json")[0])
        manifest["code_ref"] = "changed"
        save_manifest(self.store, manifest)
        with self.assertRaises(PublicationError):
            self.publisher.publish("run-1")
        self.assertEqual(self.registry(), original)

    def test_missing_file_is_not_zero_success(self):
        del self.store.data["silver/runtime/trade/runs/run-1/order_amount_checks/part-00000.parquet"]
        with self.assertRaises(PublicationError):
            self.publisher.publish("run-1")
        self.assertIsNone(self.registry())
        self.assertIsNone(self.store.get(Publisher.STATE)[0])

    def test_failed_spark_without_silver_does_not_block_next_valid_run(self):
        with self.assertRaises(PublicationError):
            self.publisher.publish("no-silver-run")
        self.assertIsNone(self.store.get(Publisher.STATE)[0])
        self.publisher.publish("run-1")
        self.assertIsNotNone(self.registry())

    def test_valid_empty_file_is_an_explicit_zero_row_run(self):
        manifest = json.loads(self.store.get("silver/runtime/trade/runs/run-1/manifest.json")[0])
        manifest["output_counts"]["order_amount_checks"] = 0
        save_manifest(self.store, manifest)
        self.store.data["silver/runtime/trade/runs/run-1/order_amount_checks/part-00000.parquet"] = parquet([], CHECK_COLUMNS)
        self.publisher.publish("run-1")
        self.assertEqual(read(self.registry())[0]["row_count"], 0)

    def test_count_mismatch_does_not_publish(self):
        manifest = json.loads(self.store.get("silver/runtime/trade/runs/run-1/manifest.json")[0])
        manifest["output_counts"]["order_amount_checks"] = 2
        save_manifest(self.store, manifest)
        with self.assertRaises(PublicationError):
            self.publisher.publish("run-1")
        self.assertIsNone(self.registry())

    def test_concurrent_publisher_cannot_take_existing_owner(self):
        state = {"owner": "active-other-owner", "pending_run_id": "run-1", "last_completed_at": None}
        self.store.data[Publisher.STATE] = encode(state)
        with self.assertRaises(PublicationError):
            self.publisher.publish("run-1")
        self.assertEqual(json.loads(self.store.get(Publisher.STATE)[0]), state)

    def test_ddl_types_and_partition_match_publication_files(self):
        for name, columns in [("silver_runs", RUN_COLUMNS), ("order_amount_checks", CHECK_COLUMNS)]:
            source = Path("pipelines/silver/" + name + ".sql").read_text(encoding="utf-8")
            body = re.search(r"CREATE EXTERNAL TABLE.*?\((.*?)\)\s*(?:PARTITIONED|STORED)", source, re.DOTALL)[1]
            parsed = [(n, t.lower()) for n, t in re.findall(r"(\w+)\s+(STRING|TIMESTAMP|BIGINT)", body)]
            self.assertEqual(parsed, columns)
            self.assertEqual("PARTITIONED BY (run_id STRING)" in source, name == "order_amount_checks")


class GlueTest(unittest.TestCase):
    def setUp(self):
        import boto3
        from botocore.stub import Stubber

        self.client = boto3.client("glue", region_name="ap-northeast-1", aws_access_key_id="testing",
                                   aws_secret_access_key="testing")
        self.stub = Stubber(self.client)
        self.store = MemoryStore()

    def test_deployed_schema_and_locations_must_match_before_writing(self):
        catalog = GlueCatalog(self.client, "silver", self.store)
        for name, columns, partitions, path in [
            ("silver_runs", RUN_COLUMNS, [], "silver/runtime/trade/catalog/completed/"),
            ("order_amount_checks", CHECK_COLUMNS, [{"Name": "run_id", "Type": "string"}],
             "silver/runtime/trade/catalog-data/runs/"),
        ]:
            table = {"Name": name, "StorageDescriptor": {
                "Columns": [{"Name": n, "Type": t} for n, t in columns],
                "Location": self.store.uri(path),
                "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"},
                "PartitionKeys": partitions}
            self.stub.add_response("get_table", {"Table": table}, {"DatabaseName": "silver", "Name": name})
        with self.stub:
            catalog.validate()
        self.assertEqual(set(catalog.tables), {"silver_runs", "order_amount_checks"})
        table["Name"] = "silver_runs"
        table["StorageDescriptor"]["Location"] = "s3://test-bucket/wrong/"
        self.stub.add_response("get_table", {"Table": table})
        with self.stub, self.assertRaises(PublicationError):
            Publisher(self.store, catalog).publish("run-1")
        self.assertIsNone(self.store.get(Publisher.STATE)[0])

    def test_partition_retries_verify_instead_of_repointing(self):
        descriptor = {"Columns": [{"Name": n, "Type": t} for n, t in CHECK_COLUMNS],
                      "Location": "s3://test-bucket/target/"}
        catalog = GlueCatalog(self.client, "silver", self.store)
        catalog.tables = {"order_amount_checks": {"StorageDescriptor": descriptor}}
        self.stub.add_response("get_partition", {"Partition": {"StorageDescriptor": descriptor,
                                                               "Parameters": {"source_manifest_sha256": "hash"}}})
        with self.stub:
            catalog.register("run-1", "s3://test-bucket/target/", "hash")
        self.stub.assert_no_pending_responses()
        self.stub.add_response("get_partition", {"Partition": {"StorageDescriptor": descriptor,
                                                               "Parameters": {"source_manifest_sha256": "different"}}})
        with self.stub, self.assertRaises(PublicationError):
            catalog.register("run-1", "s3://test-bucket/target/", "hash")

    def test_s3_compare_and_swap_uses_conditional_headers(self):
        import boto3
        from botocore.stub import Stubber

        client = boto3.client("s3", region_name="ap-northeast-1", aws_access_key_id="testing",
                              aws_secret_access_key="testing")
        stub = Stubber(client)
        store = S3Store("s3://test-bucket/root", client)
        stub.add_response("put_object", {"ETag": "v1"}, {"Bucket": "test-bucket", "Key": "root/state",
                                                         "Body": b"new", "IfNoneMatch": "*"})
        stub.add_response("put_object", {"ETag": "v2"}, {"Bucket": "test-bucket", "Key": "root/state",
                                                         "Body": b"next", "IfMatch": "v1"})
        stub.add_client_error("put_object", service_error_code="PreconditionFailed", http_status_code=412)
        with stub:
            self.assertEqual(store.put("state", b"new"), "v1")
            self.assertEqual(store.put("state", b"next", "v1"), "v2")
            with self.assertRaises(PublicationError):
                store.put("state", b"conflict", "v1")
        stub.assert_no_pending_responses()


if __name__ == "__main__":
    unittest.main()
