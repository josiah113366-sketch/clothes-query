"""spark-submit으로 실행하는 실제 Spark 4.2 거래·Parquet 비교 검증."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

try:
    from pyspark.sql import SparkSession
except ModuleNotFoundError as error:
    raise unittest.SkipTest("이 시험은 Spark 4.2 이미지에서 spark-submit으로 실행합니다") from error

from pipelines.gold_a.transactions import build_gold
from pipelines.silver.products import build_products
from pipelines.silver.transactions import build_silver
from pipelines.spark_batch import (
    build_catalog,
    build_sales,
    build_trade,
    execute,
    read_source,
)


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical(rows):
    # Parquet의 고정 스키마 NULL은 Python 딕셔너리의 선택 필드 부재와 비교한다.
    return sorted([{k: str(v) if hasattr(v, "isoformat") else v for k, v in row.items() if v is not None}
                   for row in rows], key=lambda row: json.dumps(row, default=str, sort_keys=True))


class SparkTradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os

        cls.fixture = Path(os.environ["SPARK_TEST_INPUT"])
        cls.spark = SparkSession.builder.appName("trade-parity").config("spark.sql.shuffle.partitions", "4").getOrCreate()
        cls.spark.conf.set("spark.sql.session.timeZone", "UTC")
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.base = {name: load(cls.fixture / file) for name, file in {
            "orders": "orders.jsonl", "order_items": "items.jsonl", "payments": "payments.jsonl",
            "designs": "designs.jsonl", "variants": "variants.jsonl"}.items()}

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def prepare(self, root, rows):
        paths, raw, catalog_raw = {}, None, None
        for name, records in rows.items():
            path = root / (name + ".jsonl")
            path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            paths[name] = [str(path)]
            dataset = {"designs": "product_design", "variants": "product_variant"}.get(name, name)
            frame = read_source(self.spark, dataset, [str(path)])
            if name in {"designs", "variants"}:
                catalog_raw = frame if catalog_raw is None else catalog_raw.unionByName(frame)
            else:
                raw = frame if raw is None else raw.unionByName(frame)
        return paths, raw, catalog_raw

    @staticmethod
    def rows(frame):
        return canonical([row.asDict() for row in frame.collect()])

    def test_01_normal_duplicate_retry_and_gold_match_python(self):
        data = deepcopy(self.base)
        data["payments"].append(deepcopy(data["payments"][0]))
        data["payments"][-1]["completed_at"] = "2026-10-18T15:10:00Z"
        reference = build_silver(data["orders"], data["order_items"], data["payments"], True)
        with tempfile.TemporaryDirectory() as work:
            _, raw, catalog_raw = self.prepare(Path(work), data)
            silver, catalog = build_trade(raw, input_complete=True), build_catalog(catalog_raw)
            try:
                for name in ("orders_current", "order_status_history", "silver_order_items", "payment_attempts", "order_amount_checks"):
                    self.assertEqual(self.rows(silver[name]), canonical(reference[name]), name)
                gold = build_sales(silver, catalog)
                product_rows = build_products(data["designs"], data["variants"])["silver_product_variant"]
                expected = build_gold(reference, product_rows)
                for name, frame in gold.items():
                    actual = self.rows(frame)
                    for row in actual:
                        if "sales_date_kst" in row:
                            row["sales_date_kst"] = str(row["sales_date_kst"])
                    self.assertEqual(actual, canonical(expected[name]), name)
                self.assertEqual(sum(r["duplicate_count"] for r in self.rows(silver["dq_results"])), 1)
            finally:
                for frame in silver["_cache"] + catalog["_cache"]:
                    frame.unpersist()

    def test_02_cross_order_conflict_and_unknown_item_error_match_reference(self):
        for mode in ("cross-order", "unknown-item", "amount-mismatch"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as work:
                data = deepcopy(self.base)
                if mode == "cross-order":
                    copied = deepcopy(data["payments"][0])
                    copied["order_id"] = data["orders"][1]["order_id"]
                    data["payments"].append(copied)
                elif mode == "unknown-item":
                    data["order_items"].append({"order_item_id": "unknown-item"})
                else:
                    data["orders"][0]["total_amount"] += 10000
                expected = build_silver(data["orders"], data["order_items"], data["payments"], True)
                _, raw, _ = self.prepare(Path(work), data)
                actual = build_trade(raw, input_complete=True)
                try:
                    self.assertEqual(self.rows(actual["order_amount_checks"]), canonical(expected["order_amount_checks"]))
                    for name in ("orders_current", "silver_order_items", "payment_attempts"):
                        self.assertEqual(self.rows(actual[name]), canonical(expected[name]))
                    def codes(rows):
                        return sorted((r["source_dataset"], r["record_key"] or "", r["error_code"], r["category"]) for r in rows)
                    self.assertEqual(codes(self.rows(actual["quarantined_records"])), codes(expected["quarantined_records"]))
                finally:
                    for frame in actual["_cache"]:
                        frame.unpersist()

    def test_03_parquet_publish_and_failure_preserve_previous_gold(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            paths, _, _ = self.prepare(root, deepcopy(self.base))
            request = {"job": "trade", "run_id": "first", "input_complete": True, "inputs": paths,
                       "output_root": str(root / "output")}
            result = execute(self.spark, request)
            self.assertEqual(result["status"], "PASS")
            checks = self.spark.read.parquet(str(root / "output/silver/runtime/trade/runs/first/order_amount_checks"))
            self.assertEqual(checks.schema["checked_at"].dataType.simpleString(), "timestamp")
            self.assertTrue(all(row.run_id == "first" for row in checks.collect()))
            old = (root / "output/gold_a/runtime/trade/current.json").read_bytes()
            broken = deepcopy(self.base)
            broken["orders"][0]["total_amount"] += 10000
            self.prepare(root, broken)
            with self.assertRaisesRegex(ValueError, "Silver 품질 미완료"):
                execute(self.spark, {**request, "run_id": "bad"})
            self.assertEqual((root / "output/gold_a/runtime/trade/current.json").read_bytes(), old)
            self.assertEqual(json.loads((root / "output/silver/runtime/trade/completed/bad.json").read_text())["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
