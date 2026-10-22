"""리뷰별 정제는 Executor, 상품 연결·별점/점수 집계는 Spark SQL로 수행한다."""

import csv
import io
import json
import os
import re
from datetime import date, datetime, timezone
from itertools import islice
from pathlib import Path
from uuid import uuid4

from pyspark.sql import functions as F

from pipelines.gold_a.reviews import ASPECTS, SCORE_FIELDS
from pipelines.silver.common import collect_latest, decode_record
from pipelines.silver.reviews import normalize_review
from pipelines.spark_batch import (
    SCHEMAS,
    _spark_uri,
    _write_json,
    build_catalog,
    configure_storage,
    dumps,
    read_source,
    resolve_inputs,
    save_tables,
    verify_inputs,
)

REVIEW_SCHEMA = ", ".join(f"{k} string" for k in (
    "review_id", "event_id", "product_id", "product_name", "category", "order_id",
    "created_at_utc", "created_at_kst", "review_date_kst", "emitted_at_utc", "text",
    "option_size", "option_color", "source")) + ", rating long, has_photo boolean"
METRICS = ("input_count", "accepted_count", "duplicate_count", "quarantined_count",
           "output_count", "superseded_count", "conflict_count", "pending_count", "unknown_key_error_count")


def read_documents(spark, paths, kind="reviews", model_version=None):
    def parse(files):
        for uri, text in files:
            uri = "s3://" + uri[6:] if uri.startswith("s3a://") else uri
            if uri.lower().endswith(".csv"):
                if kind != "analysis":
                    raise ValueError("CSV 입력은 모델 점수 결과만 지원합니다")
                for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
                    if row.get("score") not in {"-2", "-1", "0", "1", "2"}:
                        raise ValueError("모델 score CSV는 -2~2 정수여야 합니다")
                    yield dumps({"review_id": row.get("review_id"), "aspect": row.get("aspect"),
                                 "score": int(row["score"]), "model_version": model_version})
            else:
                for number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
                    if line.strip():
                        yield dumps(decode_record(line, uri, number))
    files = spark.sparkContext.wholeTextFiles(",".join(_spark_uri(p) for p in paths), minPartitions=2)
    return files.mapPartitions(parse)


def build_reviews(spark, documents, start, end, max_key_rows=10000):
    def key_of(text):
        row = json.loads(text)
        key = row.get("review_id")
        return ("id:" + key if isinstance(key, str) and key.strip() else
                "row:" + dumps(row["_input_source"])), row

    def process(group):
        rows = list(islice(group[1], max_key_rows + 1))
        if len(rows) > max_key_rows:
            raise ValueError("동일 리뷰 ID 입력이 행 한도를 넘습니다")
        selected, issues, quality = collect_latest(rows, "reviews", "review_id", normalize_review,
                                                   "emitted_at_utc", "reviews.v1")
        for name, values in (("silver_reviews", selected), ("quarantined_records", issues),
                             ("dq_results", [quality])):
            for value in values:
                if name == "quarantined_records":
                    value["source_record_id"] = f"reviews:{value['source_file']}:{value['source_line']}"
                yield name, dumps(value)

    tall = spark.createDataFrame(documents.map(key_of).groupByKey().flatMap(process),
                                "table_name string, payload string").persist()
    normalized = tall.filter("table_name = 'silver_reviews'").select(
        F.from_json("payload", REVIEW_SCHEMA, {"mode": "FAILFAST"}).alias("r")).select("r.*")
    selected = normalized.filter(F.col("review_date_kst").between(start, end))
    issues = tall.filter("table_name = 'quarantined_records'").select(
        F.from_json("payload", SCHEMAS["quarantined_records"], {"mode": "FAILFAST"}).alias("r")).select("r.*")
    dq = tall.filter("table_name = 'dq_results'").select(
        F.from_json("payload", ", ".join(f"{k} long" for k in METRICS)).alias("r")).select("r.*")
    summary = dq.agg(*[F.coalesce(F.sum(k), F.lit(0)).alias(k) for k in METRICS])
    # 출력 건수는 KST 범위 선택 후 계산하며 큰 키 배열 대신 상세 행으로 추적한다.
    summary = summary.drop("output_count").crossJoin(selected.agg(F.count("review_id").alias("output_count")))
    outside = normalized.filter(~F.col("review_date_kst").between(start, end)).agg(F.count("review_id").alias("outside_range_count"))
    summary = summary.crossJoin(outside).withColumn("source_dataset", F.lit("reviews")).withColumn(
        "check_version", F.lit("reviews.v1")).withColumn("status", F.when(
            F.col("quarantined_count") > 0, "INCOMPLETE").otherwise("PASS"))
    return {"silver_reviews": selected.withColumn("review_date_kst", F.to_date("review_date_kst")),
            "quarantined_records": issues, "dq_results": summary, "_cache": (tall,)}


def mapping_row(text):
    row = json.loads(text)
    if row.get("_input_error") or not all(isinstance(row.get(k), str) and row[k].strip()
                                          for k in ("product_id", "article_id")):
        raise ValueError("리뷰 상품 매핑 키 오류")
    return row["product_id"], row["article_id"]


def connect_products(reviews, catalog, mapping=None):
    variants = catalog["silver_product_variant"].select("article_id", "product_code")
    if mapping is not None:
        if mapping.filter("product_id is null or trim(product_id) = '' or article_id is null").limit(1).count():
            raise ValueError("리뷰 상품 매핑 키 오류")
        if mapping.groupBy("product_id").count().filter("count > 1").limit(1).count():
            raise ValueError("리뷰 상품 매핑 product_id 중복")
        if mapping.join(variants, "article_id", "left_anti").limit(1).count():
            raise ValueError("리뷰 상품 매핑 대상 상품 오류")
        reviews = reviews.join(mapping, "product_id", "left").withColumn("article_id", F.coalesce("article_id", "product_id"))
    else:
        reviews = reviews.withColumn("article_id", F.col("product_id"))
    if reviews.join(variants, "article_id", "left_anti").limit(1).count():
        raise ValueError("리뷰 상품 연결 실패")
    return reviews.join(variants, "article_id")


def build_product_daily(reviews):
    result = reviews.groupBy("review_date_kst", "article_id", "product_code").agg(
        F.count("review_id").alias("review_count"), F.sum("rating").alias("rating_sum"),
        F.sum(F.when(F.col("rating") <= 2, 1).otherwise(0)).alias("low_rating_count"))
    return result.withColumn("average_rating", F.round(F.col("rating_sum").cast("decimal(30,0)") /
        F.col("review_count"), 4).cast("double")).withColumn("low_rating_rate", F.round(
            F.col("low_rating_count").cast("decimal(30,0)") / F.col("review_count"), 6).cast("double"))


def build_aspects(spark, reviews, documents, model_version):
    def validate(text):
        row = json.loads(text)
        if row.get("_input_error") or not all(isinstance(row.get(k), str) and row[k].strip()
                                              for k in ("review_id", "aspect", "model_version")):
            raise ValueError("분석 결과의 키·속성·모델 버전 오류")
        if row["aspect"] not in ASPECTS or type(row.get("score")) is not int or row["score"] not in SCORE_FIELDS:
            raise ValueError("모델 속성 또는 -2~2 정수 점수 오류")
        return row["review_id"], row["aspect"], row["model_version"], row["score"]

    all_rows = spark.createDataFrame(documents.map(validate),
        "review_id string, aspect string, model_version string, score long").persist()
    try:
        selected = all_rows.filter(F.col("model_version") == model_version)
        if all_rows.limit(1).count() and not selected.limit(1).count():
            raise ValueError("요청한 모델 버전 결과가 없습니다")
        if selected.join(reviews.select("review_id"), "review_id", "left_anti").limit(1).count():
            raise ValueError("분석 결과에 Silver 범위 밖 리뷰 ID가 있습니다")
        if selected.groupBy("review_id", "aspect").agg(F.countDistinct("score").alias("n")).filter("n > 1").limit(1).count():
            raise ValueError("동일 리뷰·속성·모델 버전의 분석 내용 충돌")
        selected = selected.dropDuplicates(["review_id", "aspect", "model_version"])
        linked = selected.join(reviews.select("review_id", "review_date_kst", "article_id", "product_code"), "review_id")
        daily = linked.groupBy("review_date_kst", "article_id", "product_code", "aspect", "model_version").agg(
            F.count("review_id").alias("scored_review_count"), F.sum("score").alias("score_sum"),
            *[F.sum(F.when(F.col("score") == score, 1).otherwise(0)).alias(field) for score, field in SCORE_FIELDS.items()])
        daily = daily.withColumn("average_score", F.round(F.col("score_sum").cast("decimal(30,0)") /
                                                         F.col("scored_review_count"), 4).cast("double"))
        count = reviews.count()
        analyzed = selected.select("review_id").distinct().count()
        coverage = {"review_count": count, "reviews_with_aspect_result": analyzed,
                    "reviews_without_aspect_result": count - analyzed, "analysis_completion_status": "UNVERIFIED",
                    "note": "결과 없음은 속성 미언급 또는 미분석일 수 있습니다. 0점으로 세지 않습니다."}
        # 호출자가 저장할 때까지 캐시를 유지하고 finally에서 해제한다.
        return daily, coverage, all_rows
    except Exception:
        all_rows.unpersist()
        raise


def execute_reviews(spark, config):
    allowed = {"job", "run_id", "inputs", "output_root", "input_complete", "start_date", "end_date", "model_version", "max_key_rows"}
    if set(config) - allowed or config.get("input_complete") is not True:
        raise ValueError("지원하지 않는 리뷰 설정 또는 입력 준비 미확인")
    start, end = (date.fromisoformat(config[k]).isoformat() for k in ("start_date", "end_date"))
    if end < start:
        raise ValueError("리뷰 종료 날짜가 시작 날짜보다 빠릅니다")
    inputs = config.get("inputs", {})
    if not {"reviews", "designs", "variants"} <= set(inputs) or set(inputs) - {"reviews", "designs", "variants", "analysis", "mapping"}:
        raise ValueError("리뷰·상품 스냅샷 입력이 필요합니다")
    version = config.get("model_version")
    if "analysis" in inputs and (not isinstance(version, str) or not version.strip()):
        raise ValueError("모델 점수 입력에는 model_version이 필요합니다")
    limit = config.get("max_key_rows", 10000)
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("리뷰 ID당 행 한도는 1~100,000입니다")
    output = config.get("output_root")
    if not isinstance(output, str) or not output.strip() or output.startswith("s3a://"):
        raise ValueError("출력은 s3:// URI 또는 로컬 경로여야 합니다")
    run_id = config.get("run_id", "reviews-" + uuid4().hex)
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("run_id 형식 오류")
    if any(part in {"bronze", "ground_truth"} for part in output.replace("\\", "/").split("/")):
        raise ValueError("원천·정답표 아래에는 결과를 쓸 수 없습니다")
    for locations in inputs.values():
        if not isinstance(locations, list) or not locations:
            raise ValueError("입력별 경로 목록이 필요합니다")
        for uri in locations:
            if not isinstance(uri, str) or any(part in {"reviews_truth", "ground_truth"} for part in uri.replace("\\", "/").split("/")):
                raise ValueError("평가용 정답표를 운영 입력으로 사용할 수 없습니다")
            if "://" not in uri and not output.startswith("s3://"):
                source, target = Path(uri).resolve(), Path(output).resolve()
                if source == target or source in target.parents or target in source.parents:
                    raise ValueError("입력·출력 경로는 겹치지 않아야 합니다")
    configure_storage(spark, output)
    paths, inventory = resolve_inputs(inputs, suffixes=(".json", ".jsonl", ".csv"))
    if any(part in {"reviews_truth", "ground_truth"} for item in inventory
           for part in item["uri"].replace("\\", "/").split("/")):
        raise ValueError("입력 파일 목록에 평가용 정답표가 포함되어 있습니다")
    tables = build_reviews(spark, read_documents(spark, paths["reviews"]), start, end, limit)
    catalog, score_cache = None, None
    try:
        base = output.rstrip("/") + "/silver/runtime/reviews/runs/" + run_id
        checked = datetime.now(timezone.utc).isoformat()
        silver = save_tables(tables, base, run_id, checked)
        silver.pop("format_rules", None)
        silver.update(status="INCOMPLETE" if tables["quarantined_records"].limit(1).count() else "PASS",
                      start_date_kst=start, end_date_kst=end, check_version="reviews.v1",
                      input_objects=inventory, input_completeness="DECLARED_COMPLETE",
                      code_ref=os.environ.get("PIPELINE_CODE_REF", "unknown"), pipeline_version="spark-reviews.v1")
        publish(output, "silver", base, silver, inventory)
        if silver["status"] != "PASS":
            raise ValueError("리뷰 Silver 품질 미완료: Gold A는 갱신하지 않습니다")
        raw = read_source(spark, "product_design", [_spark_uri(p) for p in paths["designs"]]).unionByName(
            read_source(spark, "product_variant", [_spark_uri(p) for p in paths["variants"]]))
        catalog = build_catalog(raw)
        product = save_tables(catalog, base + "/products", run_id, checked)
        product.update(status="PASS")
        _write_json(base + "/products/manifest.json", product)
        stored = spark.read.parquet(_spark_uri(silver["outputs"]["silver_reviews"]))
        products = {k: spark.read.parquet(_spark_uri(p)) for k, p in product["outputs"].items()}
        mapping = None
        if "mapping" in paths:
            docs = read_documents(spark, paths["mapping"], "mapping")
            mapping = spark.createDataFrame(docs.map(mapping_row), "product_id string, article_id string")
        linked = connect_products(stored, products, mapping)
        gold_tables = {"review_product_daily": build_product_daily(linked)}
        coverage = None
        if "analysis" in paths:
            daily, coverage, score_cache = build_aspects(spark, linked,
                read_documents(spark, paths["analysis"], "analysis", version), version)
            gold_tables["review_aspect_daily"] = daily
        gold_base = output.rstrip("/") + "/gold_a/runtime/reviews/runs/" + run_id
        gold = save_tables(gold_tables, gold_base, run_id, checked)
        gold.pop("format_rules", None)
        gold.update(status="PASS", silver_manifest=base + "/manifest.json", products_manifest=base + "/products/manifest.json",
                    start_date_kst=start, end_date_kst=end, model_version=version, score_schema="score.v1",
                    review_scores="PROVIDED" if "analysis" in paths else "NOT_REQUESTED", analysis_coverage=coverage,
                    code_ref=os.environ.get("PIPELINE_CODE_REF", "unknown"))
        publish(output, "gold_a", gold_base, gold, inventory)
        return gold
    finally:
        for frame in tables["_cache"]:
            frame.unpersist()
        if catalog:
            for frame in catalog["_cache"]:
                frame.unpersist()
        if score_cache is not None:
            score_cache.unpersist()


def publish(output, layer, base, manifest, inventory):
    verify_inputs(inventory)
    channel = output.rstrip("/") + "/" + layer + "/runtime/reviews"
    _write_json(base + "/manifest.json", manifest)
    _write_json(channel + "/completed/" + manifest["run_id"] + ".json", manifest)
    _write_json(channel + "/current.json", manifest)
