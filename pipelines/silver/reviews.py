"""review.v2 Bronze JSONL을 KST 날짜별 Silver 리뷰로 정제한다.

현재 리뷰 시뮬레이터의 ``--sink lake`` 출력 경로를 입력으로 쓴다. 운영용
``reviews/``만 읽고 의도/검수 라벨이 있는 ``reviews_truth/``는 읽지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .common import RowError, collect_latest, decode_record, publish_bundle

KST = ZoneInfo("Asia/Seoul")
OUTPUT_FILE = "part-00000.jsonl"


def _uri(root: str, *parts: str) -> str:
    return "/".join((root.rstrip("/"), *(part.strip("/") for part in parts)))


def _s3_location(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 경로는 s3://버킷/접두사 형식이어야 합니다")
    return parsed.netloc, parsed.path.lstrip("/")


def _input_uris(root: str, utc_day: date) -> list[str]:
    prefix = _uri(root, "reviews", f"year={utc_day:%Y}", f"month={utc_day:%m}", f"day={utc_day:%d}")
    if prefix.startswith("s3://"):
        import boto3

        bucket, key = _s3_location(prefix)
        objects = boto3.client("s3").get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=key.rstrip("/") + "/"
        )
        return sorted(
            f"s3://{bucket}/{item['Key']}"
            for page in objects
            for item in page.get("Contents", [])
            if item["Key"].endswith(".jsonl")
        )
    return sorted(str(path) for path in Path(prefix).glob("*.jsonl"))


def _read_text(uri: str) -> str:
    if uri.startswith("s3://"):
        import boto3

        bucket, key = _s3_location(uri)
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read().decode(
            "utf-8"
        )
    return Path(uri).read_text(encoding="utf-8")


def _write_text(uri: str, body: str) -> None:
    if uri.startswith("s3://"):
        import boto3

        bucket, key = _s3_location(uri)
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/x-ndjson"
        )
        return
    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 같은 날짜를 재처리하면 파일 하나를 교체한다. 쓰다 중단돼도 기존 결과는 남는다.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".reviews-", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(body)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise RowError(field, "TYPE_MISMATCH", "시간대가 있는 ISO 시각이어야 합니다")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise RowError(field, "TYPE_MISMATCH", "시간대가 있는 ISO 시각이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RowError(field, "INVALID_VALUE", "시간대가 없습니다")
    return parsed


def normalize_review(raw: dict[str, object]) -> dict[str, object]:
    """현재 확정된 review.v2 작성 이벤트를 운영용 Silver 모양으로 바꾼다."""
    if raw.get("schema_version") != "review.v2" or raw.get("event_type") != "review_created":
        raise RowError("schema_version/event_type", "INVALID_VALUE", "지원하지 않는 리뷰 스키마 또는 이벤트 종류입니다")
    for field in ("review_id", "event_id", "product_id", "text"):
        if not isinstance(raw.get(field), str) or not str(raw[field]).strip():
            raise RowError(field, "INVALID_VALUE", "비어 있지 않은 문자열이어야 합니다")
    rating = raw.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise RowError("rating", "INVALID_VALUE", "rating은 1~5의 정수여야 합니다")
    created = _timestamp(raw.get("created_at"), "created_at")
    emitted = _timestamp(raw.get("emitted_at"), "emitted_at")
    kst = created.astimezone(KST)
    # 원천 product_id를 보존한다. 값만 보고 article_id/product_code로 임의 변환하지 않는다.
    # 개인 식별용 member_id와 평가 전용 라벨은 분석용 출력에 복사하지 않는다.
    return {
        "review_id": raw["review_id"],
        "event_id": raw["event_id"],
        "product_id": raw["product_id"],
        "product_name": raw.get("product_name"),
        "category": raw.get("category"),
        "order_id": raw.get("order_id"),
        "created_at_utc": created.astimezone(timezone.utc).isoformat(),
        "created_at_kst": kst.isoformat(),
        "review_date_kst": kst.date().isoformat(),
        "emitted_at_utc": emitted.astimezone(timezone.utc).isoformat(),
        "rating": rating,
        "text": raw["text"],
        "option_size": raw.get("option_size"),
        "option_color": raw.get("option_color"),
        "has_photo": raw.get("has_photo"),
        "source": raw.get("source"),
    }


def build_quality(input_root: str, start: date, end: date) -> tuple[dict, list[str]]:
    """읽은 범위에서 키의 오류를 확인한 뒤 KST 대상 날짜를 선택한다."""
    if end < start:
        raise ValueError("end-date가 start-date보다 빠릅니다")
    files = []
    utc_day = start - timedelta(days=1)
    while utc_day <= end:
        files.extend(_input_uris(input_root, utc_day))
        utc_day += timedelta(days=1)
    if not files:
        raise FileNotFoundError("대상 UTC 날짜 범위에 운영 리뷰 JSONL 파일이 없습니다")
    inputs = [decode_record(line, uri, number)
              for uri in files for number, line in enumerate(_read_text(uri).splitlines(), 1) if line.strip()]
    rows, issues, summary = collect_latest(
        inputs, "reviews", "review_id", normalize_review, "emitted_at_utc", "reviews.v1")
    by_day = {}
    day = start
    while day <= end:
        by_day[day.isoformat()] = []
        day += timedelta(days=1)
    for row in rows:
        if row["review_date_kst"] in by_day:
            by_day[row["review_date_kst"]].append(row)
    for selected in by_day.values():
        selected.sort(key=lambda row: (row["created_at_utc"], row["review_id"]))
    summary.update(start_date_kst=start.isoformat(), end_date_kst=end.isoformat(),
                   output_count=sum(map(len, by_day.values())),
                   outside_range_count=len(rows) - sum(map(len, by_day.values())),
                   affected_scope="REQUESTED_RANGE" if issues else None)
    # 날짜·상품을 알 수 없는 오류도 있으므로 오류가 하나라도 있으면 요청 범위를 불완전 표시한다.
    return {"by_day": by_day, "quarantined_records": issues, "dq_results": [summary]}, files


def build_reviews(input_root: str, start: date, end: date) -> dict[str, list[dict[str, object]]]:
    result, _ = build_quality(input_root, start, end)
    return result["by_day"]


def run(input_root: str, output_root: str, start: date, end: date) -> dict[str, int]:
    if input_root.startswith("s3://") and output_root.startswith("s3://"):
        source, target = input_root.rstrip("/"), output_root.rstrip("/")
        if source == target or source.startswith(target + "/") or target.startswith(source + "/"):
            raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    elif not input_root.startswith("s3://") and not output_root.startswith("s3://"):
        source, target = Path(input_root).resolve(), Path(output_root).resolve()
        if source == target or source in target.parents or target in source.parents:
            raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    result, files = build_quality(input_root, start, end)
    root = output_root if output_root.startswith("s3://") else str(Path(output_root).resolve())
    # 날짜 범위별 manifest 한 개가 정상·격리·품질 파일 전체를 함께 공개한다.
    base = _uri(root, "silver", "reviews", "scopes", f"{start}_{end}")
    payloads = {"quarantined_records.jsonl": result["quarantined_records"],
                "dq_results.jsonl": result["dq_results"]}
    for day, rows in result["by_day"].items():
        at = date.fromisoformat(day)
        payloads[f"year={at:%Y}/month={at:%m}/day={at:%d}/{OUTPUT_FILE}"] = rows
    publish_bundle(base, payloads, {
        "status": result["dq_results"][0]["status"], "check_version": "reviews.v1",
        "start_date_kst": start.isoformat(), "end_date_kst": end.isoformat(), "input_files": files,
        "input_count": result["dq_results"][0]["input_count"],
    }, _write_text)
    return {day: len(rows) for day, rows in result["by_day"].items()}


# Spark 실행에서도 위 normalize_review·collect_latest 규칙을 공유한다.
REVIEW_SCHEMA = ", ".join(f"{k} string" for k in (
    "review_id", "event_id", "product_id", "product_name", "category", "order_id",
    "created_at_utc", "created_at_kst", "review_date_kst", "emitted_at_utc", "text",
    "option_size", "option_color", "source")) + ", rating long, has_photo boolean"

METRICS = ("input_count", "accepted_count", "duplicate_count", "quarantined_count",
           "output_count", "superseded_count", "conflict_count", "pending_count", "unknown_key_error_count")


def build_reviews_spark(spark, documents, start, end, max_key_rows=10000):
    from pyspark.sql import functions as F

    from pipelines.spark_batch import SCHEMAS, dumps

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


def main() -> None:
    parser = argparse.ArgumentParser(description="review.v2 Bronze → KST Silver 리뷰")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    for day, count in run(args.input_root, args.output_root, args.start_date, args.end_date).items():
        print(f"{day}: Silver 리뷰 {count}건")
    print("품질·완료 상태 확인: " + _uri(args.output_root, "silver", "reviews", "scopes",
          f"{args.start_date}_{args.end_date}", "current.json"))


if __name__ == "__main__":
    main()
