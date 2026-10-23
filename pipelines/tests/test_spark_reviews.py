"""실제 Spark 엔진으로 리뷰 기준 함수·Parquet 공개 경계를 비교한다."""

import json
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
except ModuleNotFoundError as error:
    raise unittest.SkipTest("Spark 이미지에서 spark-submit으로 별도 실행합니다") from error

from pipelines.gold_a.reviews import (
    aggregate_aspects,
    aggregate_day,
    build_aspects,
    build_product_daily,
)
from pipelines.silver.common import collect_latest
from pipelines.silver.reviews import build_reviews_spark as build_reviews
from pipelines.silver.reviews import normalize_review
from pipelines.spark_batch import execute


def rows(frame):
    result = [{k: str(v) if hasattr(v, "isoformat") else v for k, v in row.asDict().items() if v is not None}
              for row in frame.collect()]
    return sorted(result, key=lambda row: json.dumps(row, sort_keys=True))


class SparkReviewsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = SparkSession.builder.appName("review-parity").config("spark.sql.shuffle.partitions", "4").getOrCreate()
        cls.spark.conf.set("spark.sql.session.timeZone", "UTC")
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.review = {"schema_version": "review.v2", "event_type": "review_created", "event_id": "E1",
                      "review_id": "R1", "product_id": "0000000001", "created_at": "2026-10-18T15:00:00Z",
                      "emitted_at": "2026-10-19T00:00:00Z", "rating": 2, "text": "test review", "member_id": "omit"}
        cls.scores = [{"review_id": "R1", "aspect": "품질·내구성", "score": -2, "model_version": "m1"}]

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def documents(self, values):
        return self.spark.sparkContext.parallelize([json.dumps(row) for row in values], 2)

    def input_rows(self, values):
        return [{**row, "_input_source": {"file": "fixture", "line": i}, "_input_error": None}
                for i, row in enumerate(values, 1)]

    def test_01_dates_duplicates_scores_and_reference(self):
        older = dict(self.review, emitted_at="2026-10-18T23:00:00Z", rating=5)
        outside = dict(self.review, review_id="outside", created_at="2026-10-18T14:59:59Z")
        values = self.input_rows([older, self.review, dict(self.review, created_at="2026-10-19T00:00:00+09:00"), outside])
        selected, _, ref = collect_latest(values, "reviews", "review_id", normalize_review, "emitted_at_utc", "reviews.v1")
        expected = [r for r in selected if r["review_date_kst"] == "2026-10-19"]
        tables = build_reviews(self.spark, self.documents(values), "2026-10-19", "2026-10-19")
        try:
            self.assertEqual(rows(tables["silver_reviews"]), [{k: v for k, v in r.items() if v is not None} for r in expected])
            quality = tables["dq_results"].first().asDict()
            for key in ("input_count", "accepted_count", "duplicate_count", "superseded_count"):
                self.assertEqual(quality[key], ref[key])
            self.assertEqual(quality["outside_range_count"], 1)
            self.assertNotIn("member_id", tables["silver_reviews"].columns)
            linked = tables["silver_reviews"].withColumn("article_id", F.col("product_id"))
            linked = linked.withColumn("product_code", F.lit(100).cast("long"))
            connected = [{**r, "article_id": r["product_id"], "product_code": 100} for r in expected]
            self.assertEqual(rows(build_product_daily(linked)), aggregate_day(connected, date(2026, 10, 19)))
            score_input = self.scores + self.scores + [dict(self.scores[0], model_version="m0", score=2)]
            daily, coverage, cached = build_aspects(self.spark, linked, self.documents(score_input), "m1")
            try:
                expected_daily, expected_coverage = aggregate_aspects(connected, score_input, "m1")
                self.assertEqual(rows(daily), expected_daily)
                self.assertEqual(coverage, expected_coverage)
            finally:
                cached.unpersist()
        finally:
            tables["_cache"][0].unpersist()

    def test_02_conflicts_invalid_row_and_missing_model_coverage(self):
        values = self.input_rows([self.review, dict(self.review, rating=1),
                                 dict(self.review, review_id="bad", rating=7)])
        tables = build_reviews(self.spark, self.documents(values), "2026-10-19", "2026-10-19")
        try:
            self.assertEqual(tables["silver_reviews"].count(), 0)
            self.assertEqual(tables["quarantined_records"].count(), 3)
            self.assertEqual(tables["dq_results"].first()["status"], "INCOMPLETE")
        finally:
            tables["_cache"][0].unpersist()
        connected = self.spark.createDataFrame([("R1", "2026-10-19", "0000000001", 100),
                                                 ("R2", "2026-10-19", "0000000001", 100)],
                                                "review_id string, review_date_kst string, article_id string, product_code long")
        daily, coverage, cached = build_aspects(self.spark, connected, self.documents(self.scores), "m1")
        try:
            self.assertEqual(coverage["reviews_without_aspect_result"], 1)
            self.assertEqual(daily.first()["score_zero_count"], 0)
        finally:
            cached.unpersist()
        with self.assertRaisesRegex(ValueError, "충돌"):
            build_aspects(self.spark, connected, self.documents(self.scores + [dict(self.scores[0], score=2)]), "m1")
        with self.assertRaisesRegex(ValueError, "범위 밖"):
            build_aspects(self.spark, connected, self.documents([dict(self.scores[0], review_id="unknown")]), "m1")

    def test_03_parquet_repeat_error_empty_csv_and_mapping(self):
        fixture = Path(os.environ["SPARK_TEST_INPUT"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "reviews.jsonl"
            raw.write_text(json.dumps(self.review) + "\n", encoding="utf-8")
            score = root / "scores.csv"
            score.write_text("review_id,aspect,score\nR1,품질·내구성,-2\n", encoding="utf-8")
            config = {"job": "reviews", "run_id": "good", "input_complete": True,
                      "start_date": "2026-10-19", "end_date": "2026-10-19", "model_version": "m1",
                      "output_root": str(root / "output"), "inputs": {"reviews": [str(raw)], "analysis": [str(score)],
                          "designs": [str(fixture / "designs.jsonl")], "variants": [str(fixture / "variants.jsonl")]}}
            gold = execute(self.spark, config)
            pointer = root / "output/gold_a/runtime/reviews/current.json"
            self.assertEqual(gold["output_counts"]["review_aspect_daily"], 1)
            actual = rows(self.spark.read.parquet(gold["outputs"]["review_product_daily"]))
            # 동일 리뷰를 실제 상품 시드와 같은 Parquet 기준정보로 다시 집계한다.
            for name in ("designs", "variants"):
                target = root / (name + "-parquet")
                self.spark.read.json(config["inputs"][name]).write.parquet(str(target))
                config["inputs"][name] = [str(target)]
            again = execute(self.spark, {**config, "run_id": "repeat"})
            self.assertEqual(actual, rows(self.spark.read.parquet(again["outputs"]["review_product_daily"])))
            previous = pointer.read_bytes()
            raw.write_text(json.dumps(dict(self.review, rating=7)) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "품질 미완료"):
                execute(self.spark, {**config, "run_id": "bad"})
            self.assertEqual(pointer.read_bytes(), previous)
            self.assertTrue((root / "output/silver/runtime/reviews/completed/bad.json").exists())
            raw.write_text(json.dumps(dict(self.review, product_id="alias")) + "\n", encoding="utf-8")
            mapping = root / "mapping.jsonl"
            mapping.write_text(json.dumps({"product_id": "alias", "article_id": "0000000001"}) + "\n", encoding="utf-8")
            mapped = deepcopy(config)
            mapped.update(run_id="mapped")
            mapped["inputs"]["mapping"] = [str(mapping)]
            execute(self.spark, mapped)
            raw.write_text("", encoding="utf-8")
            score.write_text("review_id,aspect,score\n", encoding="utf-8")
            empty = execute(self.spark, {**config, "run_id": "empty"})
            self.assertEqual(empty["output_counts"], {"review_product_daily": 0, "review_aspect_daily": 0})


if __name__ == "__main__":
    unittest.main()
