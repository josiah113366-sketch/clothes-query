"""Bounded Bronze ingestion, persistent click state and complete funnel snapshots.

Only new files pass through Python format validation. Historical state stays in
Parquet and is merged with Spark SQL; it is never replayed through the validator.
The publication controller advances the checkpoint only after Athena verification.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone

from pipelines.funnel_demo import Measurements, encode, read_bytes

VERSION = "funnel-incremental.v1"
STATE_SCHEMA = "event_key string, signature string, session_id string, normalized string, issue string"
CLICK_SCHEMA = ", ".join(name + " string" for name in (
    "event_id", "event_type", "member_id", "article_id", "session_id",
    "event_time_utc", "event_time_kst", "event_date_kst"))
HOLD_SCHEMA = ("table_name string, key_json string, reason string, "
               "previous_result_available boolean, last_normal_result_json string")


def ingestion_date(item):
    """UTC arrival partition is a work ordering key, not the funnel cohort."""
    match = re.search(r"/year=(\d{4})/month=(\d{2})/day=(\d{2})/", item["uri"])
    if not match:
        raise ValueError("클릭 파일에 UTC 수집 날짜 파티션이 필요합니다")
    from datetime import date
    return date(*map(int, match.groups())).isoformat()


def identity(item):
    if not isinstance(item.get("uri"), str) or "/bronze_v2/clickstream/" not in item["uri"].replace("\\", "/"):
        raise ValueError("운영 퍼널의 클릭 원본은 bronze_v2/clickstream 경로여야 합니다")
    token = item.get("etag", item.get("mtime_ns"))
    if token is None or type(item.get("size")) is not int or item["size"] < 0:
        raise ValueError("파일 위치·ETag/mtime·크기를 고정해야 합니다")
    return item["uri"], str(token), item["size"]


def plan_batch(inventory, processed=(), max_files=32, max_bytes=128 * 1024 * 1024):
    if type(max_files) is not int or not 1 <= max_files <= 128 or type(max_bytes) is not int or not 1 <= max_bytes <= 512 * 1024 * 1024:
        raise ValueError("실행 한도는 파일 1~128개, 원본 1~512MiB입니다")
    known = {row[0]: tuple(row) for row in processed}
    current = {item["uri"]: identity(item) for item in inventory}
    if len(current) != len(inventory) or any(current.get(uri) != value for uri, value in known.items()):
        raise ValueError("이미 처리한 원본이 바뀌거나 사라졌습니다; 새 기준으로 재구축해야 합니다")
    pending = sorted((item for item in inventory if item["uri"] not in known),
                     key=lambda item: (ingestion_date(item), item["uri"]))
    chosen, size = [], 0
    for item in pending:
        if item["size"] > max_bytes:
            raise ValueError("단일 원본이 묶음 용량 한도를 넘습니다; 파일을 누락시키지 않습니다")
        if chosen and (len(chosen) == max_files or size + item["size"] > max_bytes
                       or ingestion_date(item) != ingestion_date(chosen[0])):
            break
        chosen.append(item)
        size += item["size"]
    return {"objects": chosen, "bytes": size, "remaining_files": len(pending) - len(chosen),
            "ingestion_date_utc": ingestion_date(chosen[0]) if chosen else None}


def fixed_json(reference):
    if set(reference) != {"uri", "sha256"}:
        raise ValueError("고정 manifest URI·SHA256가 필요합니다")
    body = read_bytes(reference["uri"])
    if hashlib.sha256(body).hexdigest() != reference["sha256"]:
        raise ValueError("고정 manifest가 변경됐습니다")
    return json.loads(body)


def validate(config):
    required = {"job", "mode", "run_id", "output_root", "inventory", "trade", "catalog",
                "previous", "max_files", "max_bytes"}
    if (set(config) != required or config["job"] != "funnels" or config["mode"] != "incremental"
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config["run_id"])):
        raise ValueError("퍼널 증분 요청 계약이 다릅니다")
    root = config["output_root"]
    if not isinstance(root, str) or not root or any(part in {"..", "bronze", "bronze_v2", "ground_truth"}
                                                  for part in root.replace("\\", "/").split("/")):
        raise ValueError("출력은 원본과 분리한 데이터 레이크 root여야 합니다")
    if "://" in root and not root.startswith("s3://"):
        raise ValueError("출력은 S3 또는 로컬 경로여야 합니다")
    plan_batch([], max_files=config["max_files"], max_bytes=config["max_bytes"])
    return root.rstrip("/")


def normalize_partition(files):
    """FormatRules is loaded once per partition, only for newly arrived rows."""
    from pipelines.format_rules import FormatError, FormatRules
    from pipelines.silver.clicks import _normalize
    from pipelines.silver.common import RowError, decode_record
    rules = FormatRules()
    for uri, text in files:
        for number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
            if not line.strip():
                continue
            raw = decode_record(line, uri, number)
            key, session = raw.get("event_id"), raw.get("session_id")
            key = key if isinstance(key, str) and key.strip() else "invalid:" + hashlib.sha256(f"{uri}:{number}".encode()).hexdigest()
            session = session if isinstance(session, str) and session.strip() else None
            try:
                if raw.get("_input_error"):
                    raise RowError("record", "PARSE_ERROR", "JSON 객체 오류")
                normalized = encode(_normalize(raw, rules)).decode()
                yield key, hashlib.sha256(normalized.encode()).hexdigest(), session, normalized, None
            except (RowError, FormatError) as error:
                # No raw record/PII in diagnostics. Invalid IDs stay in state to
                # retain the shared rule that an invalid duplicate blocks a key.
                issue = getattr(error, "code", "INVALID_VALUE")
                yield key, "invalid:" + issue, session, None, issue


def daily_from_detail(detail):
    from pyspark.sql import functions as F
    metrics = (("view_sessions", "has_view"), ("cart_sessions", "has_cart"), ("order_sessions", "has_order"),
               ("paid_sessions", "has_paid"), ("cart_order_sessions", "ordered_after_cart"))
    daily = detail.groupBy(F.to_date(F.substring("first_view_at_kst", 1, 10)).alias("funnel_date_kst"),
                           "article_id", "product_code").agg(*[
                               F.sum(F.col(flag).cast("long")).alias(name) for name, flag in metrics])
    for name, numerator, denominator in (
        ("view_to_cart_rate", "cart_sessions", "view_sessions"), ("view_to_order_rate", "order_sessions", "view_sessions"),
        ("view_to_paid_rate", "paid_sessions", "view_sessions"), ("cart_to_order_rate", "cart_order_sessions", "cart_sessions"),
        ("order_to_paid_rate", "paid_sessions", "order_sessions")):
        daily = daily.withColumn(name, F.when(F.col(denominator) > 0, F.round(
            F.col(numerator).cast("decimal(30,0)") / F.col(denominator), 6)).cast("double"))
    return daily


def execute(spark, config):
    from pipelines.funnel_control import acquire, release, store_for
    root = validate(config)
    store = store_for(root)
    acquire(store, config)
    try:
        return _execute(spark, config)
    except Exception:
        release(store, config["run_id"])
        raise


def _execute(spark, config):
    from pyspark.sql import functions as F

    from pipelines.gold_a.funnels import build_funnels_spark
    from pipelines.spark_batch import (
        _spark_uri,
        _write_json,
        configure_storage,
        save_tables,
        verify_inputs,
    )

    root = validate(config)
    base = root + "/gold_a/runtime/funnels/runs/" + config["run_id"]
    state_base = root + "/silver/runtime/clicks/runs/" + config["run_id"]
    configure_storage(spark, root)
    timer, caches = Measurements(), []
    with timer.stage("fixed_inputs_and_plan"):
        inventory = fixed_json(config["inventory"])["objects"]
        previous = fixed_json(config["previous"]) if config["previous"] else None
        if previous and (previous.get("version") != VERSION or previous.get("output_root") != root):
            raise ValueError("이전 증분 상태의 버전·출력 root가 다릅니다")
        if previous:
            from pipelines.format_rules import FormatRules
            if previous["format_rules"]["sha256"] != FormatRules().reference()["sha256"]:
                raise ValueError("공통 규칙이 바뀌었습니다; 저장 상태를 그대로 재사용하지 말고 새 기준으로 재구축하세요")
        trade, catalog = fixed_json(config["trade"]), fixed_json(config["catalog"])
        if trade.get("status") not in {"PASS", "INCOMPLETE"} or catalog.get("status") not in {"PASS", "READY"}:
            raise ValueError("완료 거래·상품 Silver가 필요합니다")
        # Completed pointers are not substitutes for an immutable result.
        for ref, value in ((config["trade"], trade),):
            completed = ref["uri"].replace("/runs/" + value["run_id"] + "/manifest.json",
                                            "/completed/" + value["run_id"] + ".json")
            if completed == ref["uri"] or json.loads(read_bytes(completed)) != value:
                raise ValueError("Silver 완료 기록이 결과 manifest와 다릅니다")
        plan = plan_batch(inventory, (previous or {}).get("processed", []), config["max_files"], config["max_bytes"])
        verify_inputs(plan["objects"])
        if not plan["objects"] and previous and previous["trade"] == config["trade"] and previous["catalog"] == config["catalog"]:
            raise ValueError("새 입력이 없습니다; 준비 단계에서 다음 실행을 만들지 않아야 합니다")
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        with timer.stage("new_click_validation_and_state_merge"):
            incoming = (spark.createDataFrame(spark.sparkContext.wholeTextFiles(
                ",".join(_spark_uri(row["uri"]) for row in plan["objects"]),
                minPartitions=max(2, spark.sparkContext.defaultParallelism)).mapPartitions(normalize_partition), STATE_SCHEMA)
                if plan["objects"] else spark.createDataFrame([], STATE_SCHEMA))
            incoming = incoming.persist()
            caches.append(incoming)
            old = spark.read.parquet(_spark_uri(previous["click_state"])) if previous else spark.createDataFrame([], STATE_SCHEMA)
            state = old.unionByName(incoming).dropDuplicates().persist()
            caches.append(state)
            grouped = state.groupBy("event_key").agg(F.countDistinct("signature").alias("variants"),
                F.max(F.col("issue").isNotNull().cast("int")).alias("invalid"), F.first("normalized").alias("normalized"))
            bad_keys = grouped.filter("variants > 1 OR invalid > 0").select("event_key")
            blocked = state.join(bad_keys, "event_key").select("session_id").distinct()
            global_hold = bool(blocked.filter("session_id IS NULL").limit(1).count())
            clean = grouped.filter("variants = 1 AND invalid = 0").select(
                F.from_json("normalized", CLICK_SCHEMA, {"mode": "FAILFAST"}).alias("r")).select("r.*")
            state_path = state_base + "/event_state"
            state.write.mode("errorifexists").parquet(_spark_uri(state_path))
            # Persist quarantine evidence without logging source records.
            state.join(bad_keys, "event_key").write.mode("errorifexists").parquet(_spark_uri(state_base + "/quarantined_keys"))
            click_dq = grouped.agg(F.sum(F.when((F.col("variants") > 1) | (F.col("invalid") > 0), 1).otherwise(0)).alias(
                "active_error_count")).fillna(0).withColumn("source_dataset", F.lit("clickstream")).withColumn(
                    "check_version", F.lit("clicks.v2")).withColumn("status", F.when(
                        F.col("active_error_count") > 0, "INCOMPLETE").otherwise("PASS"))
            saved_clicks = save_tables({"click_events": clean.withColumn("event_date_kst", F.to_date("event_date_kst")),
                                       "dq_results": click_dq}, state_base, config["run_id"], checked_at)
            click_status = click_dq.select("status").first().status
        with timer.stage("affected_sessions_and_trade"):
            current_trade = {name: spark.read.parquet(_spark_uri(trade["outputs"][name])) for name in (
                "orders_current", "silver_order_items", "payment_attempts", "order_amount_checks", "dq_order_results")}
            orders = current_trade["orders_current"]
            affected = incoming.select("session_id")
            if not previous or previous["trade"] != config["trade"]:
                affected = affected.unionByName(orders.select("session_id"))
                if previous:
                    prior_trade = fixed_json(previous["trade"])
                    affected = affected.unionByName(spark.read.parquet(_spark_uri(
                        prior_trade["outputs"]["orders_current"])).select("session_id"))
            if previous and previous["catalog"] != config["catalog"]:
                affected = affected.unionByName(clean.select("session_id"))
            checks = current_trade["order_amount_checks"]
            nonpass = checks.filter("status IS NULL OR status != 'PASS'").select("order_id").unionByName(
                orders.select("order_id").join(checks.select("order_id"), "order_id", "left_anti"))
            nonpass = nonpass.unionByName(current_trade["dq_order_results"].filter(
                "active_error_count > 0").select("order_id")).distinct()
            nonpass = nonpass.unionByName(orders.select("order_id").join(
                current_trade["dq_order_results"].select("order_id"), "order_id", "left_anti")).distinct()
            blocked = blocked.unionByName(orders.join(nonpass, "order_id").select("session_id")).distinct()
            if "quarantined_records" in trade["outputs"]:
                issues = spark.read.parquet(_spark_uri(trade["outputs"]["quarantined_records"]))
                active = issues.filter("active IS NULL OR active = true") if "active" in issues.columns else issues
                if active.filter("order_id IS NULL").limit(1).count():
                    global_hold = True
                if "impact_candidates" in trade["outputs"]:
                    impacts = spark.read.parquet(_spark_uri(trade["outputs"]["impact_candidates"]))
                    blocked = blocked.unionByName(impacts.join(
                        active.select("source_record_id").distinct(), "source_record_id", "left_semi").select("session_id")).distinct()
            # A previously held session may recover with a new completed trade run.
            affected = affected.unionByName(blocked).filter("session_id IS NOT NULL").distinct()
            eligible = affected.join(blocked, "session_id", "left_anti")
            if global_hold:
                eligible = eligible.limit(0)
            selected_orders = orders.join(eligible, "session_id", "left_semi")
            scoped = {"orders_current": selected_orders}
            for name in ("silver_order_items", "payment_attempts"):
                scoped[name] = current_trade[name].join(selected_orders.select("order_id"), "order_id", "left_semi")
            catalog_ref = config["catalog"]
            if catalog["status"] == "READY":
                from pipelines.spark_batch import build_catalog, read_source
                verify_inputs(catalog["inventory"])
                products = build_catalog(read_source(spark, "product_design", [_spark_uri(p) for p in catalog["inputs"]["designs"]]).unionByName(
                    read_source(spark, "product_variant", [_spark_uri(p) for p in catalog["inputs"]["variants"]])))
                caches.extend(products.get("_cache", ()))
                product_base = state_base + "/products"
                saved = save_tables(products, product_base, config["run_id"], checked_at)
                saved["status"] = "PASS"
                saved["seed_inventory"] = catalog["inventory"]
                verify_inputs(catalog["inventory"])
                _write_json(product_base + "/manifest.json", saved)
                catalog_ref = {"uri": product_base + "/manifest.json", "sha256": hashlib.sha256(encode(saved)).hexdigest()}
                # _write_json formatting is not the canonical encode format.
                catalog_ref["sha256"] = hashlib.sha256(read_bytes(catalog_ref["uri"])).hexdigest()
            else:
                products = {name: spark.read.parquet(_spark_uri(catalog["outputs"][name])) for name in (
                    "silver_product_design", "silver_product_variant")}
        with timer.stage("affected_funnels_and_snapshot_save"):
            calculated = build_funnels_spark({"click_events": clean.join(eligible, "session_id", "left_semi")},
                                             scoped, products, _scoped=True)["funnel_session_product"]
            old_detail = spark.read.parquet(_spark_uri(previous["outputs"]["funnel_session_product"])) if previous else calculated.limit(0)
            detail = old_detail.join(eligible, "session_id", "left_anti").unionByName(calculated).persist()
            caches.append(detail)
            hold_rows = []
            previous_sessions = {row.session_id for row in old_detail.select("session_id").distinct().join(
                blocked, "session_id", "left_semi").limit(10001).collect()}
            for row in blocked.filter("session_id IS NOT NULL").limit(10001).collect():
                if len(hold_rows) >= 10000:
                    raise ValueError("보류 세션이 10,000개를 넘습니다; 범위를 누락시키지 않습니다")
                for table in ("funnel_session_product", "funnel_daily"):
                    hold_rows.append((table, json.dumps({"session_id": row.session_id}), "INPUT_QUALITY",
                                      row.session_id in previous_sessions, None))
            if global_hold or plan["remaining_files"]:
                for table in ("funnel_session_product", "funnel_daily"):
                    hold_rows.append((table, "{}", "UNASSIGNED_INPUT" if global_hold else "BACKFILL_IN_PROGRESS", bool(previous), None))
            holds = spark.createDataFrame(hold_rows, HOLD_SCHEMA)
            gold = save_tables({"funnel_session_product": detail, "funnel_daily": daily_from_detail(detail),
                                "refresh_holds": holds}, base, config["run_id"], checked_at)
        with timer.stage("stored_result_verification"):
            for name, uri in gold["outputs"].items():
                if spark.read.parquet(_spark_uri(uri)).count() != gold["output_counts"][name]:
                    raise ValueError("저장 결과 건수가 다릅니다")
            verify_inputs(plan["objects"])
            for reference in (config["inventory"], config["trade"], config["catalog"]):
                fixed_json(reference)
        processed = (previous or {}).get("processed", []) + [list(identity(item)) for item in plan["objects"]]
        gold.update(version=VERSION, output_root=root, status="PARTIAL" if hold_rows else "PASS",
            held_scopes=[{"table": row[0], "key": json.loads(row[1]), "reason": row[2]} for row in hold_rows],
            previous_run_id=previous["run_id"] if previous else None, trade=config["trade"], catalog=catalog_ref,
            silver_manifest=config["trade"]["uri"], products_manifest=catalog_ref["uri"],
            silver_clicks_manifest=state_base + "/manifest.json", click_state=state_path, processed=processed,
            inventory=config["inventory"], batch=plan, max_files=config["max_files"], max_bytes=config["max_bytes"],
            coverage_status="BACKFILL_IN_PROGRESS" if plan["remaining_files"] else "CAPTURED_INVENTORY_PROCESSED",
            cohort_policy="first-view-kst; full retained session history; no time cutoff",
            measurements={"stages": timer.stages, "total_seconds": round(timer.clock() - timer.started, 6),
                          "new_input_files": len(plan["objects"]), "new_input_bytes": plan["bytes"],
                          "history_processing": "Parquet SQL merge and full Gold snapshot IO; no historical Python validation"})
        saved_clicks.update(status=click_status,
                            event_state=state_path, processed=processed, coverage_status=gold["coverage_status"],
                            input_manifest=config["inventory"], batch=plan)
        _write_json(state_base + "/manifest.json", saved_clicks)
        _write_json(root + "/silver/runtime/clicks/completed/" + config["run_id"] + ".json", saved_clicks)
        _write_json(base + "/manifest.json", gold)
        _write_json(root + "/gold_a/runtime/funnels/completed/" + config["run_id"] + ".json", gold)
        return gold
    finally:
        for frame in caches:
            frame.unpersist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-uri", required=True)
    parser.add_argument("--expected-job", choices=["funnels"], default="funnels")
    args = parser.parse_args()
    config = json.loads(read_bytes(args.config_uri))
    validate(config)
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.appName("silver-gold-a-funnel-incremental").getOrCreate()
    try:
        result = execute(spark, config)
        print(encode({key: result[key] for key in ("run_id", "status")}).decode())
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
