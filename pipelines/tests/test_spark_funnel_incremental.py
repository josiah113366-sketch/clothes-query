"""Real Spark integration: bounded backfill, late payment and late click.

SPARK_FUNNEL_INPUT points at the ignored, fixed selected-session fixture. Never
prints raw input, and never accesses AWS or advances a real deployment checkpoint.
"""
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid5

try:
    from pyspark.sql import SparkSession
except ImportError as error:
    raise unittest.SkipTest("실제 Spark 이미지에서 실행합니다") from error

from pipelines.funnel_control import advance, next_request, store_for
from pipelines.funnel_demo import encode
from pipelines.funnel_incremental import execute
from pipelines.gold_a.funnels import build_funnels
from pipelines.silver.clicks import build_clicks
from pipelines.spark_batch import SCHEMAS, _write_json, resolve_inputs, save_tables


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reference(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(value))
    return {"uri": path.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class InventoryTest(unittest.TestCase):
    def test_metadata_inventory_limit_is_separate_from_bounded_work(self):
        client = Mock()
        client.get_paginator.return_value.paginate.return_value = [{"Contents": [
            {"Key": f"bronze_v2/clickstream/year=2026/month=10/day=21/{n:08}.json", "ETag": '"fixed"', "Size": 1}
            for n in range(10001)]}]
        with patch("boto3.client", return_value=client):
            with self.assertRaises(ValueError):
                resolve_inputs({"clicks": ["s3://bucket/bronze_v2/clickstream/"]})
            _, inventory = resolve_inputs({"clicks": ["s3://bucket/bronze_v2/clickstream/"]}, max_inventory_files=None)
        self.assertEqual(len(inventory), 10001)


@unittest.skipUnless(os.environ.get("SPARK_FUNNEL_INPUT"), "SPARK_FUNNEL_INPUT 고정 입력이 필요합니다")
class IncrementalSparkTest(unittest.TestCase):
    def test_backfill_and_late_changes_equal_independent_full_recomputation(self):
        fixture = Path(os.environ["SPARK_FUNNEL_INPUT"])
        spark = SparkSession.builder.appName("funnel-incremental-final-check").getOrCreate()
        spark.sparkContext.setLogLevel("ERROR")
        spark.conf.set("spark.sql.session.timeZone", "UTC")
        root = Path(tempfile.mkdtemp(prefix="funnel-final-"))
        try:
            rows = {name: load(fixture / file) for name, file in {
                "orders_current": "orders.jsonl", "silver_order_items": "items.jsonl", "payment_attempts": "payments.jsonl",
                "order_amount_checks": "checks.jsonl", "dq_order_results": "order_quality.jsonl"}.items()}
            clicks = load(fixture / "clicks.jsonl")
            staged = []
            for day, kind in (("21", "view"), ("22", "cart_add")):
                path = root / f"bronze_v2/clickstream/year=2026/month=10/day={day}/input.json"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"\n".join(encode(row) for row in clicks if row["event_type"] == kind))
                staged.append(path)

            def trade_snapshot(run, paid):
                frames = {name: spark.createDataFrame(values if paid or name != "payment_attempts" else [
                    row for row in values if row["status"] != "SUCCESS"], SCHEMAS[name]) for name, values in rows.items()}
                base = root / f"silver/runtime/trade/runs/{run}"
                saved = save_tables(frames, base.as_posix(), run, "2026-10-25T00:00:00+00:00")
                saved["status"] = "PASS"
                ref = reference(base / "manifest.json", saved)
                _write_json((root / f"silver/runtime/trade/completed/{run}.json").as_posix(), saved)
                return ref

            early_trade = trade_snapshot("trade-before-payment", False)
            complete_trade = trade_snapshot("trade-after-payment", True)
            catalog_inputs, seed_inventory = resolve_inputs({"designs": [(fixture / "designs.parquet").as_posix()],
                                                            "variants": [(fixture / "variants.parquet").as_posix()]})
            catalog = {"status": "READY", "inputs": catalog_inputs, "inventory": seed_inventory}
            catalog_ref = reference(root / "catalog.json", catalog)

            def inventory():
                _, objects = resolve_inputs({"clicks": [(root / "bronze_v2/clickstream").as_posix()]})
                return reference(root / ("inventory-" + str(len(objects)) + ".json"), {"objects": objects})

            config = {"job": "funnels", "mode": "incremental", "run_id": "backfill-one", "output_root": root.as_posix(),
                      "inventory": inventory(), "trade": early_trade, "catalog": catalog_ref, "previous": None,
                      "max_files": 1, "max_bytes": 128 * 1024 * 1024}

            def acknowledge_local(request, result):
                # Production uses real Athena verification; this local adapter
                # confirms the exact same files through Spark Parquet reads.
                for name, uri in result["outputs"].items():
                    self.assertEqual(spark.read.parquet(uri).count(), result["output_counts"][name])
                path = root / f"gold_a/runtime/funnels/runs/{result['run_id']}/manifest.json"
                advance(store_for(root.as_posix()), request, path.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest(), "local-parquet-only")

            first = execute(spark, config)
            self.assertEqual(first["status"], "PARTIAL")
            self.assertEqual(first["batch"]["remaining_files"], 1)
            self.assertEqual(spark.read.parquet(first["outputs"]["funnel_daily"]).agg({"paid_sessions": "sum"}).first()[0], 0)
            acknowledge_local(config, first)
            next_config = next_request(config)
            self.assertTrue(next_config["continue"])
            second_config = json.loads(Path(next_config["config_uri"]).read_bytes())
            second_config["trade"] = complete_trade
            second = execute(spark, second_config)
            self.assertEqual(second["status"], "PASS")
            self.assertEqual(second["batch"]["remaining_files"], 0)
            self.assertEqual(second["measurements"]["new_input_files"], 1)

            import pyarrow.parquet as pq
            products = pq.read_table(fixture / "variants.parquet").to_pylist()
            expected = build_funnels(build_clicks(clicks), dict(rows, dq_results=[{"status": "PASS", "active_error_count": 0}]), products)

            def compare(result, reference_rows):
                for name, values in reference_rows.items():
                    actual = [row.asDict() for row in spark.read.parquet(result["outputs"][name]).collect()]
                    self.assertEqual(sorted(encode(row).decode() for row in actual), sorted(encode(row).decode() for row in values))

            compare(second, expected)
            acknowledge_local(second_config, second)
            self.assertFalse(next_request(second_config)["continue"])

            # An event that arrives on the 23rd must update its original cohort,
            # not create a new funnel on the arrival day or drop unrelated days.
            target = next(row for row in expected["funnel_session_product"] if not row["has_cart"])
            raw = next(row for row in clicks if row["event_type"] == "view" and row["session_id"] == target["session_id"]
                       and row["article_id"] == target["article_id"])
            late = {**raw, "event_id": str(uuid5(UUID(int=0), "late-funnel-cart")), "event_type": "cart_add",
                    "event_time": (datetime.fromisoformat(raw["event_time"].replace("Z", "+00:00")) + timedelta(seconds=1)).isoformat()}
            path = root / "bronze_v2/clickstream/year=2026/month=10/day=23/late.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(encode(late) + b"\n" + encode(raw))  # exact duplicate across files must count once
            tip = json.loads(store_for(root.as_posix()).get("silver/runtime/clicks/catalog-control/incremental.json")[0])["tip"]
            third_config = {**second_config, "run_id": "late-click", "inventory": inventory(), "previous": tip}
            third = execute(spark, third_config)
            self.assertEqual(third["measurements"]["new_input_files"], 1)
            compare(third, build_funnels(build_clicks(clicks + [late]), dict(rows, dq_results=[{"status": "PASS", "active_error_count": 0}]), products))
            self.assertEqual(third["output_counts"]["funnel_session_product"], second["output_counts"]["funnel_session_product"])
            print(encode({"validation": "bounded-backfill-late-payment-late-click", "status": "PASS",
                          "spark": spark.version, "runs": [value["measurements"] for value in (first, second, third)]}).decode())
        finally:
            spark.stop()


if __name__ == "__main__":
    unittest.main()
