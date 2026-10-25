"""Silver 리뷰의 기본 일간 집계와 상품·기간·키워드 원문 조회."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import uuid4

from . import (
    _read_text,
    _uri,
    _write_text,
    connect_reviews,
    load_products,
    load_silver,
    read_rows,
    replacement,
    save_gold,
)

OUTPUT_FILE = "part-00000.jsonl"


def _read_scope(silver_root: str, start: date, end: date) -> tuple[dict, dict]:
    days = list(_days(start, end))
    names = [f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}" for day in days]
    manifest = _uri(silver_root, "silver", "reviews", "scopes", f"{start}_{end}", "current.json")
    loaded, reference = load_silver(manifest, {"start_date_kst": str(start), "end_date_kst": str(end)}, names)
    by_day, seen = {}, set()
    for day, name in zip(days, names):
        rows = loaded[name]
        for row in rows:
            if row.get("review_date_kst") != str(day):
                raise ValueError("Silver 리뷰 날짜가 요청 날짜와 다릅니다")
            for field in ("review_id", "product_id"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError("Silver 리뷰·상품 키가 없습니다")
            if row["review_id"] in seen:
                raise ValueError("Silver 요청 범위에 동일 review_id가 두 번 있습니다")
            seen.add(row["review_id"])
            rating = row.get("rating")
            if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
                raise ValueError("Silver 리뷰 별점이 올바르지 않습니다")
        by_day[str(day)] = rows
    return by_day, reference


def _days(start: date, end: date):
    if end < start:
        raise ValueError("end-date가 start-date보다 빠릅니다")
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def aggregate_day(rows: list[dict[str, object]], day: date) -> list[dict[str, object]]:
    """리뷰 1건을 한 번만 세고 1~2점을 낮은 별점으로 집계한다."""
    by_product: dict[str, dict[str, object]] = defaultdict(
        lambda: {"review_count": 0, "rating_sum": 0, "low_rating_count": 0}
    )
    seen: set[str] = set()
    for row in rows:
        review_id = str(row["review_id"])
        # Silver에 동일 리뷰가 두 번 있으면 조용히 두 번 세지 않고 오류를 낸다.
        if review_id in seen:
            raise ValueError("Silver 리뷰에 동일 review_id가 두 번 있습니다")
        seen.add(review_id)
        product_id = str(row.get("article_id", row.get("product_id")))
        item = by_product[product_id]
        if "article_id" in row:
            item["article_id"], item["product_code"] = row["article_id"], row["product_code"]
        rating = row["rating"]
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise ValueError("별점은 1~5 정수여야 합니다")
        item["review_count"] = int(item["review_count"]) + 1
        item["rating_sum"] = int(item["rating_sum"]) + rating
        item["low_rating_count"] = int(item["low_rating_count"]) + int(rating <= 2)

    return [
        {
            "review_date_kst": day.isoformat(),
            **({"article_id": item["article_id"], "product_code": item["product_code"]}
               if "article_id" in item else {"product_id": product_id}),
            "review_count": item["review_count"],
            "rating_sum": item["rating_sum"],
            "average_rating": ratio(item["rating_sum"], item["review_count"], 4),
            "low_rating_rate": ratio(item["low_rating_count"], item["review_count"]),
            "low_rating_count": item["low_rating_count"],
        }
        for product_id, item in sorted(by_product.items())
    ]


def ratio(numerator: int, denominator: int, places: int = 6) -> float | None:
    if denominator == 0:
        return None
    value = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    return float(value)


def _connected_scope(silver_root, start, end, products_root=None, mapping_path=None):
    by_day, ref = _read_scope(silver_root, start, end)
    refs = {"silver_reviews": ref, "start_date_kst": str(start), "end_date_kst": str(end)}
    if mapping_path and not products_root:
        raise ValueError("리뷰 매핑에는 상품 기준정보가 필요합니다")
    if products_root:
        products, catalog_ref = load_products(products_root)
        mapping = read_rows(mapping_path) if mapping_path else None
        by_day = {day: connect_reviews(rows, products, mapping) for day, rows in by_day.items()}
        refs.update(silver_products=catalog_ref, product_mapping=mapping_path,
                    product_mapping_rows=mapping or [])
    return by_day, refs


def _check_scope(reprocess, start, end):
    if reprocess and (reprocess["start_date"] < str(start) or reprocess["end_date"] > str(end)):
        raise ValueError("교체 날짜는 전체 Silver 입력 범위 안이어야 합니다")


def run_aggregate(silver_root: str, output_root: str, start: date, end: date,
                  products_root: str | None = None, mapping_path: str | None = None,
                  reprocess: dict | None = None) -> dict[str, int]:
    _check_scope(reprocess, start, end)
    by_day, refs = _connected_scope(silver_root, start, end, products_root, mapping_path)
    result, counts = {}, {}
    for day in _days(start, end):
        rows = aggregate_day(by_day[str(day)], day)
        result[f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}"] = rows
        counts[str(day)] = len(rows)
    saved = save_gold(_uri(output_root, "gold_a", "review_product_daily", "scopes", f"{start}_{end}"),
                      result, refs, reprocess)
    # 부분 재처리도 저장된 전체 범위의 행 수를 반환한다.
    return {str(day): saved["output_counts"][f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}"]
            for day in _days(start, end)}


ASPECTS = {"재질·촉감", "사이즈·핏", "색상·디자인", "품질·내구성", "가격·가성비", "냄새",
           "세탁·관리", "활용성·사용감", "배송", "포장", "교환·환불·CS"}
SCORE_FIELDS = {-2: "score_neg2_count", -1: "score_neg1_count", 0: "score_zero_count",
                1: "score_pos1_count", 2: "score_pos2_count"}
ASPECT_SCHEMA = "score.v1"


def load_analysis(path: str, model_version: str) -> list[dict]:
    if path.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(_read_text(path).lstrip("\ufeff"))))
        converted = []
        for row in rows:
            value = row.get("score")
            if value not in {"-2", "-1", "0", "1", "2"}:
                raise ValueError("모델 score CSV는 -2~2 정수여야 합니다")
            score = int(value)
            converted.append({"review_id": row.get("review_id"), "aspect": row.get("aspect"),
                              "model_version": model_version, "score": score})
        return converted
    return read_rows(path)


def aggregate_aspects(reviews: list[dict], analysis: list[dict], model_version: str) -> tuple[list[dict], dict]:
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError("분석 모델 버전이 필요합니다")
    originals = {row["review_id"]: row for row in reviews}
    if len(originals) != len(reviews):
        raise ValueError("분석 연결 대상 리뷰 ID 중복")
    selected, unknown, analyzed, matching_version = {}, set(), set(), False
    for row in analysis:
        review_id, aspect, version = (row.get(field) for field in ("review_id", "aspect", "model_version"))
        if not all(isinstance(value, str) and value.strip() for value in (review_id, aspect, version)):
            raise ValueError("분석 결과의 키·속성·모델 버전이 필요합니다")
        if aspect not in ASPECTS:
            raise ValueError("지원하지 않는 분석 속성")
        score = row.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or score not in SCORE_FIELDS:
            raise ValueError("score는 -2~2 정수여야 합니다. sentiment에서 점수를 추정하지 않습니다")
        if version != model_version:
            continue
        matching_version = True
        if review_id not in originals:
            unknown.add(review_id)
            continue
        key = (review_id, aspect)
        if key in selected and selected[key] != score:
            raise ValueError("동일 리뷰·속성·모델 버전의 분석 내용 충돌")
        selected[key] = score
        analyzed.add(review_id)
    if analysis and not matching_version:
        raise ValueError("입력에 요청한 모델 버전 결과가 없습니다")
    if unknown:
        raise ValueError("분석 결과에 Silver 범위에 없는 review_id가 있습니다")
    buckets = {}
    for (review_id, aspect), score in sorted(selected.items()):
        review = originals[review_id]
        if "article_id" not in review:
            raise ValueError("속성 집계에는 검증된 상품 연결이 필요합니다")
        key = (review["review_date_kst"], review["article_id"], aspect, model_version)
        bucket = buckets.setdefault(key, {"review_date_kst": key[0], "article_id": key[1],
            "product_code": review["product_code"], "aspect": aspect, "model_version": model_version,
            "scored_review_count": 0, "score_sum": 0, **{field: 0 for field in SCORE_FIELDS.values()}})
        bucket["scored_review_count"] += 1
        bucket["score_sum"] += score
        bucket[SCORE_FIELDS[score]] += 1
    for bucket in buckets.values():
        bucket["average_score"] = ratio(bucket["score_sum"], bucket["scored_review_count"], 4)
    coverage = {"review_count": len(originals), "reviews_with_aspect_result": len(analyzed),
                "reviews_without_aspect_result": len(originals) - len(analyzed),
                "analysis_completion_status": "UNVERIFIED",
                "note": "결과 없음은 속성 미언급 또는 미분석일 수 있습니다. 0점으로 세지 않습니다."}
    return [buckets[key] for key in sorted(buckets)], coverage


def _check_score_baseline(base: str) -> None:
    """3분류 결과에 점수 결과를 부분 병합하지 않는다. 0건 기존 결과도 버전으로 판별한다."""
    try:
        previous = json.loads(_read_text(_uri(base, "current.json")))
    except FileNotFoundError as exc:
        raise ValueError("점수 기반 전체 집계를 먼저 실행한 뒤 부분 재처리하세요") from exc
    if not isinstance(previous, dict) or previous.get("inputs", {}).get("aspect_schema") != ASPECT_SCHEMA:
        raise ValueError("기존 속성 결과 형식이 다릅니다. 원래 점수 입력으로 전체 재집계하세요")
    required = set(SCORE_FIELDS.values()) | {"scored_review_count", "score_sum", "average_score"}
    legacy = {"mentioned_review_count", "positive_review_count", "neutral_review_count", "negative_review_count", "negative_rate"}
    path = previous.get("outputs", {}).get("review_aspect_daily.jsonl")
    if not isinstance(path, str):
        raise ValueError("기존 점수 집계 파일 경로가 없습니다")  # noqa: TRY004 - 기존 결과 검증 오류 계약 유지
    if any(not required.issubset(row) or legacy.intersection(row) for row in read_rows(path)):
        raise ValueError("기존 속성 결과에 다른 형식이 섞여 있습니다. 전체 재집계하세요")


def run_aspects(silver_root: str, output_root: str, start: date, end: date, products_root: str,
                analysis_path: str, model_version: str, mapping_path: str | None = None,
                reprocess: dict | None = None) -> dict:
    _check_scope(reprocess, start, end)
    base = _uri(output_root, "gold_a", "review_aspect_daily", "scopes", f"{start}_{end}")
    if reprocess:
        _check_score_baseline(base)
    by_day, refs = _connected_scope(silver_root, start, end, products_root, mapping_path)
    analysis = load_analysis(analysis_path, model_version)
    rows, coverage = aggregate_aspects([row for group in by_day.values() for row in group], analysis, model_version)
    refs.update(analysis_path=analysis_path, model_version=model_version, analysis_coverage=coverage,
                aspect_schema=ASPECT_SCHEMA, score_policy="integer-minus2-plus2.v1")
    if reprocess:
        reprocess = {**reprocess, "model_version": model_version}
    return save_gold(base, {"review_aspect_daily.jsonl": rows}, refs, reprocess)


def search_reviews(
    silver_root: str,
    start: date,
    end: date,
    keyword: str,
    product_id: str | None = None,
    limit: int = 50,
) -> tuple[int, list[dict[str, object]]]:
    """Silver 원문에서 부분 문자열 검색. AI 감성 결과는 아직 사용하지 않는다."""
    term = keyword.strip().casefold()
    if not term:
        raise ValueError("keyword가 비어 있습니다")
    if limit < 1:
        raise ValueError("limit는 1 이상이어야 합니다")
    matches: list[dict[str, object]] = []
    by_day, _ = _read_scope(silver_root, start, end)
    for day in _days(start, end):
        for row in by_day[str(day)]:
            if product_id is not None and row["product_id"] != product_id:
                continue
            content = row.get("text")
            if not isinstance(content, str) or term not in content.casefold():
                continue
            matches.append(
                {
                    "review_id": row["review_id"],
                    "product_id": row["product_id"],
                    "product_name": row.get("product_name"),
                    "review_date_kst": row["review_date_kst"],
                    "created_at_kst": row["created_at_kst"],
                    "rating": row["rating"],
                    "text": content,
                }
            )
    matches.sort(key=lambda row: (str(row["created_at_kst"]), str(row["review_id"])), reverse=True)
    return len(matches), matches[:limit]


# 운영 실행: Spark. 위 Python 함수는 계산 검증·검색·부분 재처리에 사용한다.
def read_documents(spark, paths, kind="reviews", model_version=None):
    from pipelines.silver.common import decode_record
    from pipelines.spark_batch import _spark_uri, dumps

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


def mapping_row(text):
    row = json.loads(text)
    if row.get("_input_error") or not all(isinstance(row.get(k), str) and row[k].strip()
                                          for k in ("product_id", "article_id")):
        raise ValueError("리뷰 상품 매핑 키 오류")
    return row["product_id"], row["article_id"]


def connect_products(reviews, catalog, mapping=None):
    from pyspark.sql import functions as F

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
    from pyspark.sql import functions as F

    result = reviews.groupBy("review_date_kst", "article_id", "product_code").agg(
        F.count("review_id").alias("review_count"), F.sum("rating").alias("rating_sum"),
        F.sum(F.when(F.col("rating") <= 2, 1).otherwise(0)).alias("low_rating_count"))
    return result.withColumn("average_rating", F.round(F.col("rating_sum").cast("decimal(30,0)") /
        F.col("review_count"), 4).cast("double")).withColumn("low_rating_rate", F.round(
            F.col("low_rating_count").cast("decimal(30,0)") / F.col("review_count"), 6).cast("double"))


def build_aspects(spark, reviews, documents, model_version):
    from pyspark.sql import functions as F

    def validate(text):
        row = json.loads(text)
        if row.get("_input_error") or not all(isinstance(row.get(k), str) and row[k].strip()
                                              for k in ("review_id", "aspect", "model_version")):
            raise ValueError("분석 결과의 키·속성·모델 버전 오류")
        if row["aspect"] not in ASPECTS or type(row.get("score")) is not int or row["score"] not in SCORE_FIELDS:
            raise ValueError("모델 속성 또는 -2~2 정수 점수 오류")
        number = row.get("model_version_no")
        if model_version is None and (not isinstance(number, str) or not re.fullmatch(r"[0-9]{1,3}\.[0-9]", number)):
            raise ValueError("최신 점수의 모델 번호가 없습니다")
        return row["review_id"], row["aspect"], row["model_version"], number, row["score"]

    all_rows = spark.createDataFrame(documents.map(validate),
        "review_id string, aspect string, model_version string, model_version_no string, score long").persist()
    try:
        selected = all_rows if model_version is None else all_rows.filter(F.col("model_version") == model_version)
        if model_version is None and selected.groupBy("review_id").agg(
                F.countDistinct(F.struct("model_version", "model_version_no")).alias("n")).filter("n > 1").limit(1).count():
            raise ValueError("최신 점수 입력에 한 리뷰의 여러 모델 버전이 섞여 있습니다")
        if all_rows.limit(1).count() and not selected.limit(1).count():
            raise ValueError("요청한 모델 버전 결과가 없습니다")
        if selected.join(reviews.select("review_id"), "review_id", "left_anti").limit(1).count():
            raise ValueError("분석 결과에 Silver 범위 밖 리뷰 ID가 있습니다")
        if selected.groupBy("review_id", "aspect").agg(F.countDistinct("score").alias("n")).filter("n > 1").limit(1).count():
            raise ValueError("동일 리뷰·속성·모델 버전의 분석 내용 충돌")
        selected = selected.dropDuplicates(["review_id", "aspect", "model_version", "model_version_no"])
        linked = selected.join(reviews.select("review_id", "review_date_kst", "article_id", "product_code"), "review_id")
        daily = linked.groupBy("review_date_kst", "article_id", "product_code", "aspect", "model_version", "model_version_no").agg(
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


def _completed_review_source(config):
    """current 포인터 대신 고정된 완료 Silver와 같은 실행의 상품 기준정보를 검증한다."""
    uri = config.get("silver_manifest", "")
    if not isinstance(uri, str) or not uri:
        raise ValueError("Gold-only에는 고정 Silver manifest가 필요합니다")
    uri = uri.replace("\\", "/")
    if not uri.endswith("/manifest.json"):
        raise ValueError("Gold-only에는 고정 Silver manifest가 필요합니다")
    text = _read_text(uri)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if config.get("silver_manifest_sha256") != digest:
        raise ValueError("기존 Silver manifest 해시가 다릅니다")
    silver = json.loads(text)
    source_id = silver.get("run_id", "")
    suffix = "/silver/runtime/reviews/runs/" + source_id + "/manifest.json"
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", source_id) or not uri.endswith(suffix)
            or silver.get("status") != "PASS" or source_id == config.get("run_id")):
        raise ValueError("기존 PASS 리뷰 Silver와 다른 새 Gold 실행 ID가 필요합니다")
    root = uri[:-len(suffix)]
    if root != config["output_root"].replace("\\", "/").rstrip("/"):
        raise ValueError("Gold-only 출력은 기존 Silver와 같은 데이터 레이크 root를 사용해야 합니다")
    completed = root + "/silver/runtime/reviews/completed/" + source_id + ".json"
    if json.loads(_read_text(completed)) != silver:
        raise ValueError("기존 Silver 완료 기록과 manifest가 다릅니다")
    if any(silver.get(k + "_date_kst") != config[k + "_date"] for k in ("start", "end")):
        raise ValueError("Gold-only 날짜는 완료된 Silver 전체 범위와 같아야 합니다")
    base = uri.removesuffix("/manifest.json")
    product_uri = base + "/products/manifest.json"
    product_text = _read_text(product_uri)
    product = json.loads(product_text)
    if product.get("run_id") != source_id or product.get("status") != "PASS":
        raise ValueError("완료된 리뷰 실행의 PASS 상품 기준정보가 필요합니다")
    for manifest, prefix, required in (
            (silver, base, {"silver_reviews", "dq_results", "quarantined_records"}),
            (product, base + "/products", {"silver_product_design", "silver_product_variant"})):
        if set(manifest.get("outputs", {})) != required:
            raise ValueError("완료된 리뷰·상품 Parquet 목록이 다릅니다")
        for name in required:
            if manifest["outputs"][name].replace("\\", "/").rstrip("/") != prefix + "/" + name:
                raise ValueError("기존 결과가 고정 실행 경로 밖에 있습니다")
    return silver, product, product_uri, digest, completed, hashlib.sha256(product_text.encode("utf-8")).hexdigest()


def _load_review_parquet(spark, manifest, paths):
    from pyspark.sql.types import StructType

    from pipelines.spark_batch import _spark_uri

    tables = {}
    for name in manifest["outputs"]:
        frame = spark.read.parquet(*[_spark_uri(p) for p in paths[name]])
        if (frame.count() != manifest["output_counts"][name]
                or frame.schema.simpleString() != StructType.fromJson(manifest["schemas"][name]).simpleString()):
            raise ValueError("기존 Parquet 건수·스키마가 manifest와 다릅니다")
        tables[name] = frame
    return tables


def execute_reviews(spark, config):
    from pyspark.sql import functions as F

    from pipelines.silver.reviews import build_reviews_spark
    from pipelines.spark_batch import (
        _spark_uri,
        _write_json,
        build_catalog,
        configure_storage,
        read_source,
        resolve_inputs,
        save_tables,
    )

    allowed = {"job", "run_id", "inputs", "output_root", "input_complete", "start_date", "end_date", "model_version", "max_key_rows", "analysis_view",
               "gold_only", "silver_manifest", "silver_manifest_sha256"}
    if set(config) - allowed or config.get("input_complete") is not True:
        raise ValueError("지원하지 않는 리뷰 설정 또는 입력 준비 미확인")
    start, end = (date.fromisoformat(config[k]).isoformat() for k in ("start_date", "end_date"))
    if end < start:
        raise ValueError("리뷰 종료 날짜가 시작 날짜보다 빠릅니다")
    inputs = config.get("inputs", {})
    gold_only = config.get("gold_only", False)
    if type(gold_only) is not bool or (not gold_only and {"silver_manifest", "silver_manifest_sha256"} & set(config)):
        raise ValueError("Gold-only 설정 오류")
    if gold_only and (set(inputs) - {"mapping"} or "analysis_view" not in config):
        raise ValueError("Gold-only는 완료된 Silver·상품과 기존 Athena 점수 뷰만 사용합니다")
    if not gold_only and (not {"reviews", "designs", "variants"} <= set(inputs) or set(inputs) - {"reviews", "designs", "variants", "analysis", "mapping"}):
        raise ValueError("리뷰·상품 스냅샷 입력이 필요합니다")
    version = config.get("model_version")
    if "analysis_view" in config and ("analysis" in inputs or version is not None):
        raise ValueError("최신 점수 뷰와 파일·단일 모델 버전 입력을 함께 지정하지 마세요")
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
    if any(part in {"bronze", "bronze_v2", "ground_truth"} for part in output.replace("\\", "/").split("/")):
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
    source = _completed_review_source(config) if gold_only else None
    paths, inventory = resolve_inputs(inputs, suffixes=(".json", ".jsonl", ".csv"))
    if source:
        silver, product, product_uri, source_sha, completed_uri, product_sha = source
        inherited = {**silver["outputs"], **product["outputs"]}
        inherited_paths, inherited_inventory = resolve_inputs(
            {name: [uri.rstrip("/") + "/"] for name, uri in inherited.items()}, suffixes=(".parquet",))
        inventory.extend(inherited_inventory)
        _, manifest_inventory = resolve_inputs({"source_manifests": [config["silver_manifest"], product_uri, completed_uri]})
        inventory.extend(manifest_inventory)
    if any(part in {"reviews_truth", "ground_truth"} for item in inventory
           for part in item["uri"].replace("\\", "/").split("/")):
        raise ValueError("입력 파일 목록에 평가용 정답표가 포함되어 있습니다")
    tables = ({"_cache": ()} if gold_only else
              build_reviews_spark(spark, read_documents(spark, paths["reviews"]), start, end, limit))
    catalog, score_cache = None, None
    try:
        base = output.rstrip("/") + "/silver/runtime/reviews/runs/" + run_id
        checked = datetime.now(timezone.utc).isoformat()
        if gold_only:
            loaded = _load_review_parquet(spark, silver, inherited_paths)
            dq = loaded["dq_results"]
            stored = loaded["silver_reviews"]
            if (loaded["quarantined_records"].limit(1).count() or dq.count() != 1
                    or dq.filter("status is null or status != 'PASS'").limit(1).count()):
                raise ValueError("기존 Silver 품질 미완료: Gold A는 갱신하지 않습니다")
            if (stored.filter(F.col("review_id").isNull() | (F.trim("review_id") == "")
                              | F.col("rating").isNull() | ~F.col("rating").between(1, 5)
                              | F.col("review_date_kst").isNull()
                              | ~F.col("review_date_kst").between(start, end)).limit(1).count()
                    or stored.groupBy("review_id").count().filter("count > 1").limit(1).count()):
                raise ValueError("기존 Silver 리뷰 키·별점·날짜 오류")
            products = _load_review_parquet(spark, product, inherited_paths)
            variants = products["silver_product_variant"]
            if (variants.filter("article_id is null or product_code is null").limit(1).count()
                    or variants.groupBy("article_id").count().filter("count > 1").limit(1).count()):
                raise ValueError("기존 상품 기준정보 키 오류")
        else:
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
            product_uri = base + "/products/manifest.json"
            _write_json(product_uri, product)
            stored = spark.read.parquet(_spark_uri(silver["outputs"]["silver_reviews"]))
            products = {k: spark.read.parquet(_spark_uri(p)) for k, p in product["outputs"].items()}
        mapping = None
        if "mapping" in paths:
            docs = read_documents(spark, paths["mapping"], "mapping")
            mapping = spark.createDataFrame(docs.map(mapping_row), "product_id string, article_id string")
        linked = connect_products(stored, products, mapping)
        gold_tables = {"review_product_daily": build_product_daily(linked)}
        coverage, score_snapshot, versions = None, None, []
        if "analysis_view" in config:
            import boto3

            from pipelines.review_scores import snapshot_scores

            score_snapshot = snapshot_scores(output, run_id, start, end, config["analysis_view"],
                boto3.client("athena", region_name="ap-northeast-1"), boto3.client("s3", region_name="ap-northeast-1"))
            inventory.extend(score_snapshot["objects"])
            score_paths = [_spark_uri(item["uri"]) for item in score_snapshot["objects"]]
            scores = (spark.read.parquet(*score_paths) if score_paths else spark.createDataFrame([],
                "review_id string, aspect string, score long, model_version string, model_version_no string, review_date date"))
            if scores.filter(F.col("review_date").isNull()).limit(1).count():
                raise ValueError("모델 점수의 KST 리뷰 날짜가 없습니다")
            # KST 일자와 Silver 리뷰의 일자가 다르면 조용히 합치지 않는다.
            if scores.join(linked.select("review_id", "review_date_kst"), "review_id").filter(
                    F.col("review_date").cast("string") != F.col("review_date_kst")).limit(1).count():
                raise ValueError("모델 점수와 Silver 리뷰의 KST 날짜가 다릅니다")
            selected_versions = scores.select("model_version", "model_version_no").distinct().limit(1001).collect()
            if len(selected_versions) > 1000:
                raise ValueError("한 실행의 모델 버전 수가 1000개를 초과했습니다")
            versions = sorted([r.asDict() for r in selected_versions], key=lambda r: str(r))
            documents = scores.toJSON()
        elif "analysis" in paths:
            documents = read_documents(spark, paths["analysis"], "analysis", version)
        if "analysis_view" in config or "analysis" in paths:
            daily, coverage, score_cache = build_aspects(spark, linked, documents, version)
            gold_tables["review_aspect_daily"] = daily
        gold_base = output.rstrip("/") + "/gold_a/runtime/reviews/runs/" + run_id
        gold = save_tables(gold_tables, gold_base, run_id, checked)
        gold.pop("format_rules", None)
        gold.update(status="PASS", silver_manifest=config["silver_manifest"] if gold_only else base + "/manifest.json",
                    silver_run_id=silver["run_id"], products_manifest=product_uri,
                    start_date_kst=start, end_date_kst=end, model_version=version, score_schema="score.v1",
                    review_scores="PROVIDED" if "analysis" in paths or score_snapshot else "NOT_REQUESTED", analysis_coverage=coverage,
                    score_snapshot=score_snapshot, model_versions=versions,
                    code_ref=os.environ.get("PIPELINE_CODE_REF", "unknown"))
        if gold_only:
            if _completed_review_source(config) != source:
                raise ValueError("처리 중 기존 Silver·상품 manifest가 변경되었습니다")
            gold.update(gold_only=True, silver_manifest_sha256=source_sha,
                        products_manifest_sha256=product_sha)
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
    from pipelines.spark_batch import _write_json, verify_inputs

    verify_inputs(inventory)
    channel = output.rstrip("/") + "/" + layer + "/runtime/reviews"
    _write_json(base + "/manifest.json", manifest)
    _write_json(channel + "/completed/" + manifest["run_id"] + ".json", manifest)
    _write_json(channel + "/current.json", manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold A 리뷰 기본 집계·키워드 검색")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("aggregate", "search"):
        command = commands.add_parser(name)
        command.add_argument("--silver-root", required=True)
        command.add_argument("--start-date", type=date.fromisoformat, required=True)
        command.add_argument("--end-date", type=date.fromisoformat, required=True)
    commands.choices["aggregate"].add_argument("--output-root", required=True)
    query = commands.choices["search"]
    query.add_argument("--product-id")
    query.add_argument("--keyword", required=True)
    query.add_argument("--limit", type=int, default=50)
    query.add_argument("--output", required=True)
    aggregate = commands.choices["aggregate"]
    aggregate.add_argument("--products-root")
    aggregate.add_argument("--mapping-path")
    aspect = commands.add_parser("aspects")
    for option in ("silver-root", "output-root", "products-root", "analysis-path", "model-version"):
        aspect.add_argument("--" + option, required=True)
    aspect.add_argument("--start-date", type=date.fromisoformat, required=True)
    aspect.add_argument("--end-date", type=date.fromisoformat, required=True)
    aspect.add_argument("--mapping-path")
    for command in (aggregate, aspect):
        command.add_argument("--replace-start-date")
        command.add_argument("--replace-end-date")
        command.add_argument("--article-id", action="append")
    args = parser.parse_args()
    if args.command == "aggregate":
        for day, count in run_aggregate(
            args.silver_root, args.output_root, args.start_date, args.end_date, args.products_root, args.mapping_path,
            replacement(args.replace_start_date, args.replace_end_date, args.article_id)
        ).items():
            print(f"{day}: 상품별 리뷰 집계 {count}행")
    elif args.command == "aspects":
        result = run_aspects(args.silver_root, args.output_root, args.start_date, args.end_date,
                             args.products_root, args.analysis_path, args.model_version, args.mapping_path,
                             replacement(args.replace_start_date, args.replace_end_date, args.article_id))
        print("속성 집계 완료: " + result["manifest_path"])
    else:
        total, rows = search_reviews(
            args.silver_root, args.start_date, args.end_date, args.keyword, args.product_id, args.limit
        )
        _write_text(
            args.output,
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        )
        # 콘솔에는 리뷰 원문이나 개인 정보를 출력하지 않는다.
        print(f"검색 결과 {total}건 중 {len(rows)}건 저장: {args.output}")


if __name__ == "__main__":
    main()
