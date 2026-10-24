"""spark-submit으로 실행하는 실제 Spark 4.2 거래·Parquet 비교 검증."""

import json
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
except ModuleNotFoundError as error:
    raise unittest.SkipTest("이 시험은 Spark 4.2 이미지에서 spark-submit으로 실행합니다") from error

from pipelines.gold_a.funnels import build_funnels, build_funnels_spark
from pipelines.gold_a.transactions import build_gold
from pipelines.silver.clicks import build_clicks, build_clicks_spark
from pipelines.silver.products import build_products
from pipelines.silver.transactions import build_silver
from pipelines.spark_batch import (
    build_catalog,
    build_sales,
    build_trade,
    execute,
    read_source,
    resolve_inputs,
)


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical(rows):
    # Parquet의 고정 스키마 NULL은 Python 딕셔너리의 선택 필드 부재와 비교한다.
    return sorted([{k: str(v) if hasattr(v, "isoformat") else v for k, v in row.items() if v is not None}
                   for row in rows], key=lambda row: json.dumps(row, default=str, sort_keys=True))


def check_gold_ddl(manifest):
    from pipelines.gold_publication import TYPES
    sql = (Path(__file__).resolve().parents[1] / "gold_a/tables.sql").read_text(encoding="utf-8")
    for name, schema in manifest["schemas"].items():
        body = re.search(r"gold_a\." + name + r"_runs\s*\((.*?)\)\s*PARTITIONED", sql, re.DOTALL)[1]
        expected = [tuple(token.strip().lower().split()) for token in body.split(",")]
        actual = [(field["name"], TYPES[field["type"]]) for field in schema["fields"]]
        assert actual == expected, name


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
        data["payments"][0]["completed_at"] = "2026-10-18T15:10:00.1234Z"
        data["payments"].append(deepcopy(data["payments"][0]))
        data["payments"][-1]["completed_at"] = "2026-10-18T15:10:00.123400+00:00"
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

    def test_10_payment_update_historical_error_matches_reference(self):
        data = deepcopy(self.base)
        first = data["payments"][0]
        trace = {"kafka_topic": "payments", "kafka_partition": 0,
                 "kafka_timestamp": "2026-10-21T00:00:00.000Z", "kafka_timestamp_type": "CreateTime", "__op": "u"}
        data["payments"][0] = {**first, **trace, "kafka_offset": 10, "__source_ts_ms": 1000, "amount": "bad"}
        data["payments"].append({**first, **trace, "kafka_offset": 11, "__source_ts_ms": 1001, "pg": "PG_B"})
        reference = build_silver(data["orders"], data["order_items"], data["payments"], True)
        with tempfile.TemporaryDirectory() as work:
            _, raw, _ = self.prepare(Path(work), data)
            actual = build_trade(raw, input_complete=True)
            try:
                self.assertEqual(self.rows(actual["payment_attempts"]), canonical(reference["payment_attempts"]))
                issues = self.rows(actual["quarantined_records"])
                self.assertEqual(len(issues), 1)
                self.assertFalse(issues[0]["active"])
                self.assertEqual(actual["dq_results"].filter("status <> 'PASS'").count(), 0)
            finally:
                for frame in actual["_cache"]:
                    frame.unpersist()

    def test_09_partial_reprocess_preserves_other_orders_and_recovers_mismatch(self):
        from pipelines.reprocess import read_json
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            data = deepcopy(self.base)
            inputs = {}
            for name, records in data.items():
                path = root / (name + ".jsonl")
                path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
                inputs[name] = [str(path)]
            output = str(root / "output")
            config = {"job": "trade", "input_complete": True, "inputs": inputs, "output_root": output}
            baseline = execute(self.spark, {**config, "run_id": "baseline"})
            check_gold_ddl(baseline)
            old, _ = read_json(baseline["silver_manifest"])
            target, other = data["orders"][0]["order_id"], data["orders"][1]["order_id"]
            other_amount = data["orders"][1]["total_amount"]

            def scoped(run):
                current, _ = read_json(output + "/silver/runtime/trade/current.json")
                uri = output + "/silver/runtime/trade/runs/" + current["run_id"] + "/manifest.json"
                _, digest = read_json(uri)
                current_gold, _ = read_json(output + "/gold_a/runtime/trade/current.json")
                return {**config, "run_id": run, "reprocess_scope": {"order_ids": [target],
                    "window_start": "2026-10-18T00:00:00Z", "window_end": "2026-10-20T00:00:00Z",
                    "previous_silver": uri, "previous_sha256": digest, "previous_gold_run_id": current_gold["run_id"]}}

            data["orders"][0]["total_amount"] += 10000
            data["orders"][1]["total_amount"] += 777  # 승인 밖 변경은 이번 결과에 섞이지 않아야 한다.
            Path(inputs["orders"][0]).write_text("".join(json.dumps(row) + "\n" for row in data["orders"]), encoding="utf-8")
            partial = execute(self.spark, scoped("partial"))
            self.assertEqual(partial["status"], "PARTIAL")
            patched, _ = read_json(partial["silver_manifest"])
            checks = self.rows(self.spark.read.parquet(patched["outputs"]["order_amount_checks"]))
            self.assertEqual(next(r for r in checks if r["order_id"] == target)["status"], "MISMATCH")
            self.assertEqual(next(r for r in checks if r["order_id"] == other)["order_total_amount"], other_amount)
            self.assertTrue(all(r["run_id"] == "partial" for r in checks))
            self.assertEqual(patched["actual_scope"]["order_ids"], [target])
            self.assertEqual(old["run_id"], "baseline")
            data["orders"][0]["total_amount"] -= 10000
            Path(inputs["orders"][0]).write_text("".join(json.dumps(row) + "\n" for row in data["orders"]), encoding="utf-8")
            recovered = execute(self.spark, scoped("recovered"))
            self.assertEqual(recovered["status"], "PASS")
            self.assertEqual(recovered["held_scopes"], [])
            restored, _ = read_json(recovered["silver_manifest"])
            checks = self.rows(self.spark.read.parquet(restored["outputs"]["order_amount_checks"]))
            self.assertEqual(next(r for r in checks if r["order_id"] == target)["status"], "PASS")
            self.assertEqual(next(r for r in checks if r["order_id"] == other)["order_total_amount"], other_amount)

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
            old = {name: self.rows(self.spark.read.parquet(path)) for name, path in result["outputs"].items()
                   if name != "refresh_holds"}
            broken = deepcopy(self.base)
            broken["orders"][0]["total_amount"] += 10000
            self.prepare(root, broken)
            partial = execute(self.spark, {**request, "run_id": "bad"})
            self.assertEqual(partial["status"], "PARTIAL")
            self.assertTrue(all(not scope["key"] for scope in partial["held_scopes"]))
            for name, expected in old.items():
                self.assertEqual(self.rows(self.spark.read.parquet(partial["outputs"][name])), expected)
            self.assertEqual(json.loads((root / "output/silver/runtime/trade/completed/bad.json").read_text())["status"], "INCOMPLETE")


    def click_file(self, root, values):
        path = root / "clicks.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")
        return str(path)

    def test_04_clicks_funnels_dates_retry_and_reference(self):
        data = deepcopy(self.base)
        values = load(self.fixture / "clicks.jsonl")
        values[0]["event_time"] = "2026-10-18T10:00:00.123456+09:00"
        duplicate = dict(values[0], event_time="2026-10-18T01:00:00.123456Z")
        values.append(duplicate)
        values.append(dict(values[0], event_id=str(uuid4()), event_type="cart_add", event_time="2026-10-18T09:00:00+09:00"))
        values.append(dict(values[0], event_id=str(uuid4()), article_id="0000000002"))
        values.append(dict(values[0], event_id=str(uuid4()), session_id=str(uuid4()), event_type="cart_add"))
        success = data["payments"][0]
        data["payments"].append(dict(success, payment_id=str(uuid4()), attempt_no=1, status="FAILED",
                                     failure_code="PG_TIMEOUT", completed_at=success["requested_at"]))
        success["attempt_no"] = 2
        ref_clicks = build_clicks(values)
        ref_trade = build_silver(data["orders"], data["order_items"], data["payments"], True)
        variants = build_products(data["designs"], data["variants"])["silver_product_variant"]
        expected = build_funnels(ref_clicks, ref_trade, variants)
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            _, raw, product_raw = self.prepare(root, data)
            click_tables = build_clicks_spark(self.spark, [self.click_file(root, values)])
            trade, catalog = build_trade(raw, input_complete=True), build_catalog(product_raw)
            try:
                self.assertEqual(self.rows(click_tables["click_events"]), canonical(ref_clicks["click_events"]))
                quality = click_tables["dq_results"].first().asDict()
                for key in ("input_count", "accepted_count", "duplicate_count", "quarantined_count"):
                    self.assertEqual(quality[key], ref_clicks["dq_results"][0][key])
                actual = build_funnels_spark(click_tables, trade, catalog)
                for name, table in actual.items():
                    self.assertEqual(self.rows(table), canonical(expected[name]), name)
                direct = next(row for row in self.rows(actual["funnel_session_product"])
                              if row["session_id"] == data["orders"][1]["session_id"])
                self.assertTrue(direct["has_paid"])
                self.assertFalse(direct["has_cart"])
                empty = {**click_tables, "click_events": click_tables["click_events"].limit(0)}
                self.assertEqual(build_funnels_spark(empty, trade, catalog)["funnel_daily"].count(), 0)
            finally:
                for frame in click_tables["_cache"] + trade["_cache"] + catalog["_cache"]:
                    frame.unpersist()

    def test_05_click_conflicts_missing_product_and_bad_payment_time(self):
        values = load(self.fixture / "clicks.jsonl")
        broken = values + [dict(values[0], article_id="0000000002"), dict(values[1], event_id=str(uuid4()), event_type="bad")]
        reference = build_clicks(broken)
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            bad = build_clicks_spark(self.spark, [self.click_file(root, broken)])
            try:
                codes = lambda rows: sorted((r["record_key"] or "", r["error_code"], r["category"]) for r in rows)
                self.assertEqual(codes(self.rows(bad["quarantined_records"])), codes(reference["quarantined_records"]))
                self.assertEqual(bad["dq_results"].first()["status"], "INCOMPLETE")
            finally:
                bad["_cache"][0].unpersist()
            _, raw, product_raw = self.prepare(root, deepcopy(self.base))
            trade, catalog = build_trade(raw, input_complete=True), build_catalog(product_raw)
            click_tables = build_clicks_spark(self.spark, [self.click_file(root, values)])
            try:
                altered = {**click_tables, "click_events": click_tables["click_events"].withColumn("article_id", F.lit("9999999999"))}
                with self.assertRaisesRegex(ValueError, "상품 연결"):
                    build_funnels_spark(altered, trade, catalog)
                early = {**trade, "payment_attempts": trade["payment_attempts"].withColumn("completed_at_utc", F.lit("2026-10-17T00:00:00Z"))}
                with self.assertRaisesRegex(ValueError, "빠른"):
                    build_funnels_spark(click_tables, early, catalog)
                duplicate = {**trade, "payment_attempts": trade["payment_attempts"].unionByName(trade["payment_attempts"].filter("status='SUCCESS'"))}
                with self.assertRaisesRegex(ValueError, "성공 결제 중복"):
                    build_funnels_spark(click_tables, duplicate, catalog)
            finally:
                for frame in click_tables["_cache"] + trade["_cache"] + catalog["_cache"]:
                    frame.unpersist()

    def test_06_funnel_parquet_reprocess_and_click_error_preserve_gold(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            paths, _, _ = self.prepare(root, deepcopy(self.base))
            values = load(self.fixture / "clicks.jsonl")
            paths["clicks"] = [self.click_file(root, values)]
            config = {"job": "funnels", "run_id": "funnel1", "input_complete": True,
                      "inputs": paths, "output_root": str(root / "output")}
            result = execute(self.spark, config)
            check_gold_ddl(result)
            actual = {name: self.rows(self.spark.read.parquet(path)) for name, path in result["outputs"].items()}
            again = execute(self.spark, {**config, "run_id": "funnel2"})
            for name, path in again["outputs"].items():
                self.assertEqual(actual[name], self.rows(self.spark.read.parquet(path)))
            changed = deepcopy(self.base)
            changed["payments"][-1].update(status="SUCCESS", failure_code=None)
            self.prepare(root, changed)
            self.click_file(root, values + [dict(values[0], event_time="2026-10-17T10:00:00+09:00")])
            partial = execute(self.spark, {**config, "run_id": "funnel-bad"})
            self.assertEqual(partial["status"], "PARTIAL")
            partial_daily = self.rows(self.spark.read.parquet(partial["outputs"]["funnel_daily"]))
            self.assertEqual(next(r for r in partial_daily if r["article_id"] == "0000000002")["paid_sessions"], 1)
            self.assertEqual(next(r for r in partial_daily if r["article_id"] == "0000000001"),
                             next(r for r in actual["funnel_daily"] if r["article_id"] == "0000000001"))
            self.assertTrue(any(h["key"].get("funnel_date_kst") == "2026-10-17" for h in partial["held_scopes"]))
            check = json.loads((root / "output/silver/runtime/clicks/completed/funnel-bad.json").read_text())
            self.assertEqual(check["status"], "INCOMPLETE")
            self.assertTrue((root / "output/silver/runtime/trade/completed/funnel-bad.json").exists())
            self.click_file(root, values)
            restored = execute(self.spark, {**config, "run_id": "funnel-restored"})
            self.assertEqual(restored["status"], "PASS")
            self.assertEqual(restored["held_scopes"], [])

    def test_07_payment_conflict_scopes_repeat_and_recovery(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            paths, _, _ = self.prepare(root, deepcopy(self.base))
            config = {"job": "trade", "run_id": "normal", "input_complete": True, "inputs": paths,
                      "output_root": str(root / "output")}
            baseline = execute(self.spark, config)
            data = deepcopy(self.base)
            data["payments"][-1].update(status="SUCCESS", failure_code=None)
            data["payments"].append(dict(data["payments"][0], amount=99999, completed_at="2026-10-19T01:10:00+09:00"))
            self.prepare(root, data)
            partial = execute(self.spark, {**config, "run_id": "conflict"})
            self.assertEqual(partial["status"], "PARTIAL")
            self.assertTrue(all(h["key"] for h in partial["held_scopes"]))
            hours = [h["key"].get("hour_start_kst") for h in partial["held_scopes"]]
            self.assertIn("2026-10-19T00:00:00+09:00", hours)
            self.assertIn("2026-10-19T01:00:00+09:00", hours)
            daily = self.rows(self.spark.read.parquet(partial["outputs"]["product_sales_daily"]))
            self.assertEqual(next(r for r in daily if r["article_id"] == "0000000002")["paid_order_count"], 1)
            self.assertEqual(next(r for r in daily if r["article_id"] == "0000000001" and r["sales_date_kst"] == "2026-10-19")["item_sales_amount"], 20000)
            repeated = execute(self.spark, {**config, "run_id": "conflict-again"})
            self.assertEqual([h["last_normal_result"] for h in repeated["held_scopes"]],
                             [h["last_normal_result"] for h in partial["held_scopes"]])
            self.assertTrue(any(h["last_normal_result"] and h["last_normal_result"]["run_id"] == baseline["run_id"]
                                for h in repeated["held_scopes"]))
            data["payments"].pop()
            self.prepare(root, data)
            recovered = execute(self.spark, {**config, "run_id": "recovered"})
            self.assertEqual(recovered["status"], "PASS")
            self.assertEqual(recovered["held_scopes"], [])
            self.assertEqual(recovered["output_counts"]["refresh_holds"], 0)

    def test_08_first_run_hold_without_previous_is_not_false_zero(self):
        from pipelines.gold_a import merge_spark_scopes

        fresh = {"order_sales_hourly": self.spark.createDataFrame([], "hour_start_kst string, order_count long, paid_order_count long, approved_amount long")}
        holds = [{"table": "order_sales_hourly", "key": {}, "reason": "UNKNOWN_SCOPE"}]
        merged = merge_spark_scopes(fresh, {}, holds, None)
        self.assertEqual(merged["order_sales_hourly"].count(), 0)
        self.assertFalse(holds[0]["previous_result_available"])
        self.assertIsNone(holds[0]["last_normal_result"])
        self.assertEqual(merged["refresh_holds"].count(), 1)
        self.assertIsNone(merged["refresh_holds"].first()["last_normal_result_json"])
        from pipelines.gold_a import plan_spark_holds
        from pipelines.spark_batch import SCHEMAS

        trade = {"impact_candidates": self.spark.createDataFrame([], SCHEMAS["impact_candidates"]),
                 "quarantined_records": self.spark.createDataFrame([("payments", "X", None)] * 1001,
                     "source_dataset string, record_key string, order_id string")}
        capped = plan_spark_holds(trade, None, ["order_sales_hourly", "product_sales_daily"])[0]
        self.assertTrue(all(not h["key"] and h["reason"] == "SCOPE_METADATA_LIMIT" for h in capped))
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "previous")
            fresh["order_sales_hourly"].write.parquet(path)
            previous = {"status": "PARTIAL", "outputs": {"order_sales_hourly": path},
                        "held_scopes": [{"table": "order_sales_hourly", "key": {}}]}
            small = {**trade, "quarantined_records": trade["quarantined_records"].limit(1)}
            guarded = plan_spark_holds(small, previous, ["order_sales_hourly"])[0]
            self.assertEqual(guarded[0]["reason"], "PREVIOUS_UNRESOLVED_SCOPE")



    def test_09_product_parquet_trade_and_funnels(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            paths, _, _ = self.prepare(root, deepcopy(self.base))
            for name in ("designs", "variants"):
                target = root / (name + "-parquet")
                self.spark.read.json(paths[name]).write.parquet(str(target))
                paths[name] = [str(target)]
            resolved, inventory = resolve_inputs(paths)
            self.assertTrue(all(item["uri"].endswith(".parquet") for item in inventory
                                if item["dataset"] in {"designs", "variants"}))
            self.assertTrue(all(resolved[name] for name in ("designs", "variants")))
            config = {"job": "trade", "run_id": "parquet-trade", "input_complete": True,
                      "inputs": paths, "output_root": str(root / "output")}
            gold = execute(self.spark, config)
            self.assertEqual(gold["status"], "PASS")
            reference = build_gold(build_silver(self.base["orders"], self.base["order_items"], self.base["payments"], True),
                                   build_products(self.base["designs"], self.base["variants"])["silver_product_variant"])
            for name in reference:
                self.assertEqual(self.rows(self.spark.read.parquet(gold["outputs"][name])), canonical(reference[name]))
            paths["clicks"] = [str(self.fixture / "clicks.jsonl")]
            funnel = execute(self.spark, {**config, "job": "funnels", "run_id": "parquet-funnels"})
            self.assertEqual(funnel["status"], "PASS")
            self.assertGreater(funnel["output_counts"]["funnel_session_product"], 0)

    def test_10_product_parquet_validation_and_mixed_duplicate(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            paths, _, catalog_raw = self.prepare(root, deepcopy(self.base))
            target = root / "variants-parquet"
            self.spark.read.json(paths["variants"]).write.parquet(str(target))
            raw = read_source(self.spark, "product_variant", [paths["variants"][0], *resolve_inputs(
                {"variants": [str(target)]})[0]["variants"]])
            design = read_source(self.spark, "product_design", paths["designs"])
            catalog = build_catalog(raw.unionByName(design))
            try:
                self.assertEqual(self.rows(catalog["silver_product_variant"]),
                                 canonical(build_products(self.base["designs"], self.base["variants"])["silver_product_variant"]))
                self.assertTrue(all(row.article_id.startswith("0") for row in catalog["silver_product_variant"].collect()))
            finally:
                for frame in catalog["_cache"]:
                    frame.unpersist()
            for mode in ("conflict", "wrong-type", "missing-reference"):
                with self.subTest(mode=mode):
                    bad = self.spark.read.json(paths["variants"])
                    if mode == "conflict":
                        bad = bad.withColumn("price", F.col("price") + 100)
                    elif mode == "wrong-type":
                        bad = bad.withColumn("price", F.col("price").cast("string"))
                    else:
                        bad = bad.withColumn("product_code", F.lit(999999999).cast("long"))
                    target = root / mode
                    bad.write.parquet(str(target))
                    files = resolve_inputs({"variants": [str(target)]})[0]["variants"]
                    invalid = read_source(self.spark, "product_variant", files)
                    if mode == "conflict":
                        invalid = invalid.unionByName(catalog_raw)
                    else:
                        invalid = invalid.unionByName(design)
                    with self.assertRaisesRegex(ValueError, "상품 기준정보"):
                        build_catalog(invalid)
            with self.assertRaisesRegex(ValueError, "상품 기준정보만"):
                read_source(self.spark, "payments", files)


if __name__ == "__main__":
    unittest.main()
