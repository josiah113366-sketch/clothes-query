"""Spark 거래·리뷰 배치 진입점과 입력 고정·Parquet 저장 공통 기능."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from pipelines.format_rules import DEFAULT_RULES, FormatError, FormatRules
from pipelines.payment_fingerprint import FingerprintError
from pipelines.silver import clicks, products, transactions
from pipelines.silver.common import (
    RowError,
    decode_record,
    integer,
    kafka_reference,
    required_text,
)

KEYS = {"orders": "order_id", "order_items": "order_item_id", "payments": "payment_id",
        "product_design": "product_code", "product_variant": "article_id"}
TABLES = ("orders_current", "order_status_history", "silver_order_items", "payment_attempts",
          "quarantined_records", "dq_results", "order_amount_checks", "impact_candidates")
RAW_SCHEMA = "dataset string, record_key string, order_id string, source_id string, raw string, signature string, version_kind string, version_key string, issue string"
TALL_SCHEMA = "table_name string, payload string"
ORDER_FIELDS = "order_id string, member_id string, session_id string, status string, status_reason string, total_amount long, ordered_at_utc string, ordered_at_kst string, updated_at_utc string, updated_at_kst string, source_ts_ms long"
SCHEMAS = {
    "orders_current": ORDER_FIELDS,
    "order_status_history": "order_id string, previous_status string, status string, status_reason string, changed_at_utc string, changed_at_kst string, source_ts_ms long",
    "silver_order_items": "order_item_id string, order_id string, article_id string, quantity long, unit_price long, item_amount long",
    "payment_attempts": "payment_id string, order_id string, attempt_no long, method string, pg string, amount long, status string, failure_code string, requested_at_utc string, requested_at_kst string, completed_at_utc string, completed_at_kst string, payment_content_hash string, fingerprint_version string",
    "quarantined_records": "source_dataset string, source_row_number long, source_file string, source_line long, source_record_id string, record_key string, order_id string, field string, error_code string, reason string, category string, rule_id string, check_version string, order_total_amount long, item_total_amount long, amount_difference long, kafka_reference string",
    "order_amount_checks": "order_id string, check_name string, check_version string, status string, order_total_amount long, item_total_amount long, amount_difference long",
    "impact_candidates": "source_dataset string, source_row_number long, source_record_id string, valid boolean, order_id string, order_item_id string, payment_id string, article_id string, session_id string, status string, ordered_at string, updated_at string, completed_at string, cdc_op string, source_ts_ms long, source string",
    "silver_product_design": ", ".join(f"{name} long" for name in products.DESIGN_INTEGERS) + ", " + ", ".join(f"{name} string" for name in products.DESIGN_TEXT),
    "silver_product_variant": ", ".join(f"{name} long" for name in products.VARIANT_INTEGERS) + ", " + ", ".join(f"{name} string" for name in products.VARIANT_TEXT),
}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_partition(dataset, files, rules_path, source_format="jsonl"):
    rules = FormatRules(rules_path)
    for uri, number, line in files:
        uri = "s3://" + uri[6:] if uri.startswith("s3a://") else uri
        if not line.strip():
            continue
        raw = decode_record(line, uri, number)
        source = raw["_input_source"]
        if source_format == "parquet":
            source["format"] = "parquet"
            source["position_kind"] = "execution_row_ordinal"
        source["kafka"] = kafka_reference(raw)
        source_id = f"{dataset}:{uri}:{number}"
        key = raw.get(KEYS[dataset])
        key = (str(key) if type(key) is int else key) if dataset == "product_design" else key
        key = key if isinstance(key, str) and key.strip() else None
        order_id = raw.get("order_id")
        order_id = order_id if isinstance(order_id, str) and order_id.strip() else None
        issue, normalized = None, None
        kind, version = "", ""
        try:
            if raw.get("_input_error"):
                raise RowError("record", raw["_input_error"], "업무 행 JSON 객체를 읽을 수 없습니다")
            if dataset in {"orders", "order_items", "payments"}:
                if any(name in raw for name in ("before", "after", "payload", "op")):
                    raise RuntimeError("펼쳐진 CDC 입력이 필요합니다")
                transactions._check_cdc(raw, dataset)
                rules.validate(dataset, raw)
                normalize = {"orders": transactions._order, "order_items": transactions._item,
                             "payments": transactions._payment}[dataset]
                normalized = normalize(raw)
                if dataset == "orders":
                    kind, at = transactions._version(raw, normalized)
                    version = str(at)
            else:
                ints = products.DESIGN_INTEGERS if dataset == "product_design" else products.VARIANT_INTEGERS
                texts = products.DESIGN_TEXT if dataset == "product_design" else products.VARIANT_TEXT
                normalized = {**{k: integer(raw, k) for k in ints}, **{k: required_text(raw, k) for k in texts}}
        except (RowError, FormatError, FingerprintError) as error:
            issue = {"field": error.field, "error_code": getattr(error, "code", "INVALID_VALUE"),
                     "reason": str(error), "category": "INVALID"}
            if isinstance(error, FormatError):
                issue["rule_id"] = error.rule_id
        signature = (normalized["payment_content_hash"] if dataset == "payments" else dumps(normalized)) if normalized else None
        yield dataset, key, order_id, source_id, dumps(raw), signature, kind, version, dumps(issue) if issue else None


def read_source(spark, dataset, paths, rules_path=DEFAULT_RULES):
    if not paths:
        raise ValueError("입력 파일 목록이 비어 있습니다: " + dataset)
    parquet = [path for path in paths if path.endswith(".parquet")]
    if parquet and dataset not in {"product_design", "product_variant"}:
        raise ValueError("Parquet 원천 입력은 상품 기준정보만 지원합니다")
    frames = []
    if parquet:
        source = spark.read.parquet(*parquet)
        # 원본 타입을 캐스팅하지 않고 기존 상품 검사에 전달한다. ID 선행 0도 보존한다.
        documents = source.select(F.input_file_name().alias("uri"),
                                 F.to_json(F.struct(*[source[c] for c in source.columns]),
                                           {"ignoreNullFields": "false"}).alias("payload"))
        records = documents.rdd.zipWithIndex().map(lambda pair: (
            pair[0].uri, pair[1] + 1, pair[0].payload))
        frames.append(spark.createDataFrame(records.mapPartitions(
            lambda rows: _normalize_partition(dataset, rows, str(rules_path), "parquet")), RAW_SCHEMA))
    # 파일 단위 읽기는 Executor에서 한다. Sink 분할 파일 기준이며 Driver에 원문을 수집하지 않는다.
    text_paths = [path for path in paths if not path.endswith(".parquet")]
    if text_paths:
        rdd = spark.sparkContext.wholeTextFiles(",".join(text_paths), minPartitions=max(2, spark.sparkContext.defaultParallelism))
        records = rdd.flatMap(lambda pair: ((pair[0], number, line)
            for number, line in enumerate(pair[1].lstrip("\ufeff").splitlines(), 1)))
        frames.append(spark.createDataFrame(records.mapPartitions(
            lambda rows: _normalize_partition(dataset, rows, str(rules_path))), RAW_SCHEMA))
    result = frames[0]
    for frame in frames[1:]:
        result = result.unionByName(frame)
    return result


def global_issues(raw):
    """주문별 분산 처리 전에 주문 경계를 넘는 PK 충돌까지 검사한다."""
    keyed = raw.filter(F.col("record_key").isNotNull())
    groups = keyed.groupBy("dataset", "record_key").agg(
        F.max(F.col("issue").isNotNull().cast("int")).alias("has_invalid"),
        F.countDistinct(F.when(F.col("issue").isNull(), F.col("signature"))).alias("contents"),
        F.countDistinct(F.when(F.col("issue").isNull(), F.col("version_kind"))).alias("kinds"))
    conflicts = keyed.filter((F.col("dataset") == "orders") & F.col("issue").isNull()).groupBy(
        "dataset", "record_key", "version_kind", "version_key").agg(F.countDistinct("signature").alias("n")).filter(
            "n > 1").select("dataset", "record_key").distinct().withColumn("order_conflict", F.lit(True))
    joined = raw.join(groups, ["dataset", "record_key"], "left").join(conflicts, ["dataset", "record_key"], "left")

    def issue(field, code, message, category):
        return F.to_json(F.struct(field.alias("field"), F.lit(code).alias("error_code"),
                                 F.lit(message).alias("reason"), F.lit(category).alias("category")))
    key_field = F.create_map(*[item for pair in KEYS.items() for item in (F.lit(pair[0]), F.lit(pair[1]))])[F.col("dataset")]
    conflict = F.when(F.col("dataset") == "orders", F.coalesce("order_conflict", F.lit(False))).otherwise(F.col("contents") > 1)
    return joined.withColumn("global_issue", F.coalesce(
        F.col("issue"),
        F.when(F.col("has_invalid") == 1, issue(key_field, "UNTRUSTED_GROUP", "같은 키의 오류 기록이 있어 결과 확정을 보류합니다", "DEPENDENCY_BLOCKED")),
        F.when(conflict, issue(F.when(F.col("dataset") == "orders", F.lit("updated_at")).otherwise(key_field),
                              "CONTENT_CONFLICT", "동일 키의 업무 내용이 다릅니다", "CONFLICT")),
        F.when((F.col("dataset") == "orders") & (F.col("kinds") > 1), issue(F.lit("__source_ts_ms"),
                    "AMBIGUOUS_ORDER", "동일 주문에 CDC 행과 업무 행이 섞여 순서를 확정할 수 없습니다", "CONFLICT"))
    ))


def _restore_order(group, rules_path, input_complete, unknown_item, max_rows):
    rows = list(islice(group, max_rows + 1))
    if len(rows) > max_rows:
        raise ValueError("한 주문의 변경·항목·결제 행 수가 실행 한도를 초과했습니다. 잘라 처리하지 않습니다")
    rows.sort(key=lambda r: r.source_id)
    inputs = {name: [] for name in ("orders", "order_items", "payments")}
    initial = {name: {} for name in inputs}
    sources = {}
    for row in rows:
        index = len(inputs[row.dataset])
        inputs[row.dataset].append(json.loads(row.raw))
        sources[row.dataset, index + 1] = row.source_id
        if row.global_issue:
            initial[row.dataset][index] = json.loads(row.global_issue)
    result = transactions.build_silver(inputs["orders"], inputs["order_items"], inputs["payments"], input_complete,
        FormatRules(rules_path), _initial_errors=initial, _unlinked_item_error=unknown_item)
    for table, records in result.items():
        for record in records:
            if table in {"impact_candidates", "quarantined_records"}:
                record["source_record_id"] = sources[record["source_dataset"], record["source_row_number"]]
            for key in ("source", "kafka_reference", "format_rules"):
                if isinstance(record.get(key), dict):
                    record[key] = dumps(record[key])
            # 상세는 분산된 별도 테이블 행으로 보존하고 거대한 품질 배열은 모으지 않는다.
            if table == "dq_results":
                for key in ("amount_checks", "affected_order_ids", "source_row_numbers", "output_counts"):
                    record.pop(key, None)
            yield table, dumps(record)


def build_trade(raw, rules_path=DEFAULT_RULES, input_complete=False, max_order_rows=10000):
    raw = raw.persist()
    checked = global_issues(raw).persist()
    unknown = bool(checked.filter((F.col("dataset") == "order_items") & F.col("order_id").isNull()
                                  & F.col("global_issue").isNotNull()).limit(1).count())
    groups = checked.rdd.map(lambda row: (row.order_id or "unknown:" + row.source_id, row)).groupByKey()
    tall = raw.sparkSession.createDataFrame(groups.flatMap(lambda pair: _restore_order(
        pair[1], str(rules_path), input_complete, unknown, max_order_rows)), TALL_SCHEMA).persist()
    tables = {name: tall.filter(F.col("table_name") == name).select(
        F.from_json("payload", schema, {"mode": "FAILFAST"}).alias("r")).select("r.*")
        for name, schema in SCHEMAS.items() if name not in {"silver_product_design", "silver_product_variant"}}
    metrics = ("input_count", "accepted_count", "quarantined_count", "duplicate_count", "conflict_count", "pending_count")
    dq = tall.filter("table_name = 'dq_results'").select(F.from_json("payload",
        "source_dataset string, " + ", ".join(f"{key} long" for key in metrics)).alias("r")).select("r.*")
    # 오류 분류는 원천 행의 최종 격리 결과를 기준으로 집계한다.
    summary = dq.groupBy("source_dataset").agg(*[F.sum(key).alias(key) for key in metrics])
    datasets = raw.sparkSession.createDataFrame([(name,) for name in ("orders", "order_items", "payments")], "source_dataset string")
    summary = datasets.join(summary, "source_dataset", "left").fillna(0)
    rule_ref = dumps(FormatRules(rules_path).reference())
    tables["dq_results"] = summary.withColumn("status", F.when(F.col("quarantined_count") > 0, "INCOMPLETE").otherwise("PASS"))
    tables["dq_results"] = tables["dq_results"].withColumn("check_version", F.lit(transactions.CHECK_VERSION)).withColumn("format_rules", F.lit(rule_ref))
    tables["_cache"] = (raw, checked, tall)
    return tables


def kafka_observations(raw):
    fields = {"state": "status", "topic": "topic", "partition": "partition", "offset": "offset"}
    trace = raw.select("dataset", *[F.get_json_object("raw", "$._input_source.kafka." + path).alias(name)
                                    for name, path in fields.items()])
    result = {name: {"contract": "kafka-trace.draft.v1", "coverage_status": "UNVERIFIED",
                     "row_counts": {"VALID": 0, "INVALID": 0, "MISSING": 0}, "partitions": []}
              for name in ("orders", "order_items", "payments")}
    for row in trace.groupBy("dataset", "state").count().collect():
        result[row.dataset]["row_counts"][row.state] = row["count"]
    positions = trace.filter("topic is not null and partition is not null and offset is not null").withColumn(
        "partition", F.col("partition").cast("long")).withColumn("offset", F.col("offset").cast("long"))
    observations = positions.groupBy("dataset", "topic", "partition").agg(
        F.min("offset").alias("min_offset"), F.max("offset").alias("max_offset"), F.count("offset").alias("row_count"),
        F.countDistinct("offset").alias("unique_offset_count")).limit(10001).collect()
    if len(observations) > 10000:
        raise ValueError("원본 Kafka 관측 파티션 수가 실행기 메타데이터 한도를 넘습니다")
    for row in observations:
        value = row.asDict()
        name = value.pop("dataset")
        result[name]["partitions"].append(value)
    return result


def build_catalog(raw):
    checked = global_issues(raw).persist()
    good = checked.filter(F.col("global_issue").isNull())
    good = good.dropDuplicates(["dataset", "record_key"])
    designs = good.filter("dataset = 'product_design'").select(F.from_json("signature", SCHEMAS["silver_product_design"], {"mode": "FAILFAST"}).alias("r")).select("r.*")
    variants = good.filter("dataset = 'product_variant'").select(F.from_json("signature", SCHEMAS["silver_product_variant"], {"mode": "FAILFAST"}).alias("r")).select("r.*")
    missing = variants.join(designs.select("product_code"), "product_code", "left_anti")
    if checked.filter(F.col("global_issue").isNotNull()).limit(1).count() or missing.limit(1).count():
        checked.unpersist()
        raise ValueError("상품 기준정보 품질 오류·연결 누락: 정상 판매 집계로 공개하지 않습니다")
    return {"silver_product_design": designs, "silver_product_variant": variants, "_cache": (checked,)}


def build_sales(tables, catalog):
    orders, items, payments = tables["orders_current"], tables["silver_order_items"], tables["payment_attempts"]
    variants = catalog["silver_product_variant"].select("article_id", "product_code")
    if items.join(variants, "article_id", "left_anti").limit(1).count():
        raise ValueError("판매 상품 기준정보 연결 실패")
    # UTC 세션에서 원천 오프셋을 해석한 뒤 KST 업무 시간으로 변환한다.
    def kst(field):
        return F.from_utc_timestamp(F.to_timestamp(field), "Asia/Seoul")
    hours = orders.groupBy(F.date_trunc("hour", kst("ordered_at_utc")).alias("hour")).agg(F.count("order_id").alias("order_count"))
    successful = payments.filter("status = 'SUCCESS'").withColumn("paid_at", kst("completed_at_utc"))
    paid = successful.groupBy(F.date_trunc("hour", "paid_at").alias("hour")).agg(
        F.countDistinct("order_id").alias("paid_order_count"), F.sum("amount").alias("approved_amount"))
    hourly = hours.join(paid, "hour", "full").fillna(0).select(
        F.concat(F.date_format("hour", "yyyy-MM-dd'T'HH:mm:ss"), F.lit("+09:00")).alias("hour_start_kst"),
        "order_count", "paid_order_count", "approved_amount")
    daily = successful.select("order_id", F.to_date("paid_at").alias("sales_date_kst")).join(items, "order_id").join(variants, "article_id").groupBy(
        "sales_date_kst", "article_id", "product_code").agg(F.countDistinct("order_id").alias("paid_order_count"),
            F.sum("quantity").alias("sold_quantity"), F.sum("item_amount").alias("item_sales_amount"))
    return {"order_sales_hourly": hourly, "product_sales_daily": daily}


def location(uri):
    parsed = urlsplit(uri)
    parts = PurePosixPath(parsed.path).parts
    if (parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment
            or ".." in parts or "\\" in uri):
        raise ValueError("시간 제한 서명 URL 대신 s3://버킷/경로를 지정하세요")
    return parsed.netloc, parsed.path.lstrip("/")

def _write_json(uri, value):
    if uri.startswith("s3://"):
        import boto3

        bucket, key = location(uri)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=dumps(value).encode("utf-8"),
                                      ContentType="application/json")
    else:
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(dumps(value), encoding="utf-8")
        os.replace(temp, path)


def _spark_uri(uri):
    return "s3a://" + uri[5:] if uri.startswith("s3://") else uri


def resolve_inputs(inputs, suffixes=(".json", ".jsonl")):
    """Driver는 파일 메타데이터만 고정한다. 파일 내용은 Executor가 읽는다."""
    resolved, inventory = {}, []
    seen = set()
    for name, locations in inputs.items():
        allowed_suffixes = tuple(suffixes) + ((".parquet",) if name in {"designs", "variants"} else ())
        if not isinstance(locations, list) or not locations:
            raise ValueError("입력별 파일 또는 접두사 목록이 필요합니다")
        files = []
        for uri in locations:
            if uri.startswith("s3://"):
                import boto3

                client = boto3.client("s3")
                bucket, key = location(uri)
                if not key:
                    raise ValueError("버킷 전체 대신 데이터셋 접두사를 지정하세요")
                objects = (item for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key)
                           for item in page.get("Contents", [])) if uri.endswith("/") else [
                    {"Key": key, **client.head_object(Bucket=bucket, Key=key)}]
                for obj in objects:
                    if not obj["Key"].endswith(allowed_suffixes):
                        continue
                    path = f"s3://{bucket}/{obj['Key']}"
                    files.append(path)
                    inventory.append({"dataset": name, "uri": path, "etag": obj["ETag"],
                                      "size": obj.get("Size", obj.get("ContentLength"))})
            elif "://" not in uri:
                path = Path(uri).resolve()
                paths = sorted(path.rglob("*")) if path.is_dir() else [path]
                for path in paths:
                    if path.suffix not in allowed_suffixes or not path.is_file():
                        continue
                    files.append(str(path))
                    inventory.append({"dataset": name, "uri": str(path), "size": path.stat().st_size,
                                      "mtime_ns": path.stat().st_mtime_ns})
            else:
                raise ValueError("S3 URI 또는 로컬 파일 경로가 필요합니다")
        if not files:
            raise FileNotFoundError("입력 파일이 없습니다: " + name)
        for path in files:
            if path in seen:
                raise ValueError("중복·겹친 입력 파일이 있습니다")
            seen.add(path)
        if len(inventory) > 10000 or any(item["size"] > 64 * 1024 * 1024 for item in inventory):
            raise ValueError("첫 실행 한도: 10,000개 파일, 파일당 64MiB. 초과 시 임의로 자르지 않습니다")
        resolved[name] = sorted(files)
    return resolved, inventory


def verify_inputs(inventory):
    for item in inventory:
        uri = item["uri"]
        if uri.startswith("s3://"):
            import boto3

            bucket, key = location(uri)
            if boto3.client("s3").head_object(Bucket=bucket, Key=key)["ETag"] != item["etag"]:
                raise ValueError("처리 중 원본 객체가 변경되어 결과를 공개하지 않습니다")
        elif Path(uri).stat().st_mtime_ns != item["mtime_ns"]:
            raise ValueError("처리 중 원본 파일이 변경되어 결과를 공개하지 않습니다")


def save_tables(tables, base, run_id, checked_at):
    outputs, counts, schemas = {}, {}, {}
    for name, frame in tables.items():
        if name.startswith("_"):
            continue
        if name == "order_amount_checks":
            frame = frame.withColumn("run_id", F.lit(run_id)).withColumn("checked_at", F.to_timestamp(F.lit(checked_at))).withColumn("source_manifest", F.lit(base + "/manifest.json"))
        for field in frame.columns:
            if field.endswith("_utc"):
                frame = frame.withColumn(field, F.to_timestamp(field))
        target = base + "/" + name
        counts[name] = frame.count()
        frame.write.mode("errorifexists").parquet(_spark_uri(target))
        outputs[name], schemas[name] = target, frame.schema.jsonValue()
    return {"run_id": run_id, "checked_at": checked_at, "outputs": outputs, "output_counts": counts,
            "schemas": schemas, "coverage_status": "UNVERIFIED", "format_rules": FormatRules().reference(),
            "engine": "spark", "spark_version": tables[next(k for k in tables if not k.startswith('_'))].sparkSession.version,
            "spark_application_id": tables[next(k for k in tables if not k.startswith('_'))].sparkSession.sparkContext.applicationId}


def configure_storage(spark, output):
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    spark.conf.set("spark.sql.parquet.outputTimestampType", "TIMESTAMP_MICROS")
    if output.startswith("s3://"):
        spark.conf.set("spark.sql.sources.commitProtocolClass", "org.apache.spark.internal.io.cloud.PathOutputCommitProtocol")
        spark.conf.set("spark.sql.parquet.output.committer.class", "org.apache.spark.internal.io.cloud.BindingParquetOutputCommitter")
        spark.sparkContext._jsc.hadoopConfiguration().set("fs.s3a.committer.name", "magic")
        spark.sparkContext._jsc.hadoopConfiguration().set("fs.s3a.committer.magic.enabled", "true")
        # 실행별 고유 출력 경로에만 쓴다. 같은 경로의 다른 작업 MPU를 중단할 수 있다.
        spark.sparkContext._jsc.hadoopConfiguration().set("fs.s3a.committer.abort.pending.uploads", "true")
        spark.sparkContext._jsc.hadoopConfiguration().set("mapreduce.outputcommitter.factory.scheme.s3a", "org.apache.hadoop.fs.s3a.commit.S3ACommitterFactory")


def execute(spark, config):
    if isinstance(config, dict) and config.get("job") == "reviews":
        from pipelines.gold_a.reviews import execute_reviews

        return execute_reviews(spark, config)
    if not isinstance(config, dict) or set(config) - {"job", "run_id", "inputs", "output_root", "input_complete", "max_order_rows", "max_click_rows"}:
        raise ValueError("지원하지 않는 Spark 실행 설정 필드입니다")
    if config.get("job") not in {"trade", "funnels"} or config.get("input_complete") is not True:
        raise ValueError("거래·퍼널 실행에는 전체 이력·참조 입력 준비 확인이 필요합니다")
    job = config["job"]
    names = {"orders", "order_items", "payments", "designs", "variants"}
    if job == "funnels":
        names.add("clicks")
    if set(config.get("inputs", {})) != names:
        raise ValueError("거래·상품 스냅샷 및 퍼널 작업의 클릭 입력을 확인하세요")
    output = config.get("output_root")
    if not isinstance(output, str) or not output.strip() or output.startswith("s3a://"):
        raise ValueError("출력은 s3:// URI 또는 로컬 경로로 지정하세요")
    if output.startswith("s3://"):
        if set(location(output)[1].split("/")) & {"bronze", "ground_truth"}:
            raise ValueError("Bronze·정답표 아래에는 결과를 쓸 수 없습니다")
    else:
        target = Path(output).resolve()
        for paths in config["inputs"].values():
            for path in paths:
                if "://" not in path:
                    source = Path(path).resolve()
                    if target == source or target in source.parents or source in target.parents:
                        raise ValueError("입력·출력 경로는 겹치지 않아야 합니다")
    run_id = config.get("run_id", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-") + uuid4().hex)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("run_id는 영문·숫자·하이픈·밑줄 1~100자리입니다")
    configure_storage(spark, output)
    if type(config.get("max_order_rows", 10000)) is not int or not 1 <= config.get("max_order_rows", 10000) <= 100000:
        raise ValueError("주문당 행 한도는 1~100,000입니다")
    if type(config.get("max_click_rows", 10000)) is not int or not 1 <= config.get("max_click_rows", 10000) <= 100000:
        raise ValueError("클릭 ID당 행 한도는 1~100,000입니다")
    inputs, inventory = resolve_inputs(config["inputs"])
    raw = None
    for name in ("orders", "order_items", "payments"):
        source = read_source(spark, name, [_spark_uri(p) for p in inputs[name]])
        raw = source if raw is None else raw.unionByName(source)
    tables = build_trade(raw, input_complete=True, max_order_rows=config.get("max_order_rows", 10000))
    output = config["output_root"].rstrip("/")
    base = output + "/silver/runtime/trade/runs/" + run_id
    tables["_cache"][-1].count()
    checked_at = datetime.now(timezone.utc).isoformat()
    click_tables, click_manifest = None, None
    try:
        silver = save_tables(tables, base, run_id, checked_at)
        silver.update(status="INCOMPLETE" if tables["quarantined_records"].limit(1).count() else "PASS", inputs=inputs,
                      input_objects=inventory, input_completeness="DECLARED_COMPLETE",
                      kafka_observations=kafka_observations(tables["_cache"][0]), pipeline_version="spark-trade.v1",
                      code_ref=os.environ.get("PIPELINE_CODE_REF", "unknown"), check_version=transactions.CHECK_VERSION)
        verify_inputs(inventory)
        _write_json(base + "/manifest.json", silver)
        channel = output + "/silver/runtime/trade"
        _write_json(channel + "/completed/" + run_id + ".json", silver)
        _write_json(channel + "/current.json", silver)
        if job == "funnels":
            click_tables = clicks.build_clicks_spark(spark, inputs["clicks"], max_key_rows=config.get("max_click_rows", 10000))
            click_base = output + "/silver/runtime/clicks/runs/" + run_id
            click_manifest = save_tables(click_tables, click_base, run_id, checked_at)
            click_manifest.update(status="INCOMPLETE" if click_tables["quarantined_records"].limit(1).count() else "PASS",
                                  input_objects=[item for item in inventory if item["dataset"] == "clicks"],
                                  input_completeness="DECLARED_COMPLETE", check_version=clicks.CHECK_VERSION,
                                  code_ref=os.environ.get("PIPELINE_CODE_REF", "unknown"))
            verify_inputs(inventory)
            _write_json(click_base + "/manifest.json", click_manifest)
            channel = output + "/silver/runtime/clicks"
            _write_json(channel + "/completed/" + run_id + ".json", click_manifest)
            _write_json(channel + "/current.json", click_manifest)
        product_raw = read_source(spark, "product_design", [_spark_uri(p) for p in inputs["designs"]]).unionByName(
            read_source(spark, "product_variant", [_spark_uri(p) for p in inputs["variants"]]))
        catalog = build_catalog(product_raw)
        try:
            gold_base = output + "/gold_a/runtime/" + job + "/runs/" + run_id
            product_manifest = save_tables(catalog, base + "/products", run_id, checked_at)
            product_manifest["status"] = "PASS"
            _write_json(base + "/products/manifest.json", product_manifest)
            stored = {name: spark.read.parquet(_spark_uri(path)) for name, path in silver["outputs"].items()}
            stored_catalog = {name: spark.read.parquet(_spark_uri(path)) for name, path in product_manifest["outputs"].items()}
            from pipelines.gold_a import (
                merge_spark_scopes,
                plan_spark_holds,
                previous_spark_gold,
            )

            names = (["funnel_session_product", "funnel_daily"] if job == "funnels" else
                     ["order_sales_hourly", "product_sales_daily"])
            channel = output + "/gold_a/runtime/" + job
            previous = previous_spark_gold(channel)
            stored_clicks = ({name: spark.read.parquet(_spark_uri(path)) for name, path in click_manifest["outputs"].items()}
                             if click_manifest else None)
            holds, affected, context, click_context, pairs, prior_tables = plan_spark_holds(stored, previous, names, stored_clicks)
            entire_hold = any(not row["key"] for row in holds)
            healthy = dict(stored)
            for name in ("orders_current", "silver_order_items", "payment_attempts"):
                if entire_hold:
                    healthy[name] = stored[name].limit(0)
                elif affected:
                    healthy[name] = stored[name].filter(~F.col("order_id").isin(sorted(affected)))
            if job == "funnels":
                from pipelines.gold_a.funnels import build_funnels_spark

                healthy_clicks = dict(stored_clicks)
                if entire_hold:
                    healthy_clicks["click_events"] = stored_clicks["click_events"].limit(0)
                elif pairs:
                    pair_frame = spark.createDataFrame(pairs, "session_id string, article_id string")
                    healthy_clicks["click_events"] = stored_clicks["click_events"].join(pair_frame, ["session_id", "article_id"], "left_anti")
                gold_tables = build_funnels_spark(healthy_clicks, healthy, stored_catalog, _scoped=bool(holds))
            else:
                gold_tables = build_sales(healthy, stored_catalog)
            gold_tables = merge_spark_scopes(gold_tables, prior_tables, holds, previous)
            gold = save_tables(gold_tables, gold_base, run_id, checked_at)
            gold.update(status="PARTIAL" if holds else "PASS", silver_manifest=base + "/manifest.json",
                        products_manifest=base + "/products/manifest.json", held_scopes=holds,
                        held_context=context if holds else [], held_click_context=click_context if holds else [],
                        published_at=datetime.now(timezone.utc).isoformat(), previous_run_id=(previous or {}).get("run_id"),
                        check_version="gold-a.spark-scoped.v1")
            if job == "funnels":
                gold.update(silver_clicks_manifest=click_base + "/manifest.json",
                            cohort_policy="first-view-kst; same-session-product; entire-supplied-history; no-cutoff")
            verify_inputs(inventory)
            _write_json(gold_base + "/manifest.json", gold)
            channel = output + "/gold_a/runtime/" + job
            _write_json(channel + "/completed/" + run_id + ".json", gold)
            _write_json(channel + "/current.json", gold)
            return gold
        finally:
            for cached in catalog["_cache"]:
                cached.unpersist()
    finally:
        if click_tables is not None:
            for cached in click_tables["_cache"]:
                cached.unpersist()
        for cached in tables["_cache"]:
            cached.unpersist()


def main():
    parser = argparse.ArgumentParser(description="Spark Silver → Gold A 거래·리뷰·퍼널 집계")
    parser.add_argument("--config-uri", required=True)
    args = parser.parse_args()
    if args.config_uri.startswith("s3://"):
        import boto3

        bucket, key = location(args.config_uri)
        config = json.loads(boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read())
    else:
        config = json.loads(Path(args.config_uri).read_text(encoding="utf-8"))
    spark = SparkSession.builder.appName("silver-gold-a-" + str(config.get("job", "unknown"))).getOrCreate()
    try:
        result = execute(spark, config)
        print(dumps({"run_id": result["run_id"], "status": result["status"], "output_counts": result["output_counts"]}))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
