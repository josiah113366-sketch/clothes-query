"""Audited Gold-only recovery from immutable, complete Spark Silver.

No Bronze/Silver mutation. Synthetic exclusions are exact dataset/key pairs,
never a prefix or error-class exclusion. Unknown impact retains a whole-table
hold. A new run and a signed-by-hash policy preserve the recovery evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

KEYS = {"orders": "order_id", "order_items": "order_item_id", "payments": "payment_id"}
NAMES = ("order_sales_hourly", "product_sales_daily")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def policy_keys(policy):
    if (set(policy) != {"version", "approval", "source_run_id", "records", "expected_excluded_active_errors"}
            or policy["version"] != 1 or policy["approval"] != "exclude-confirmed-synthetic-tests-only"
            or not 1 <= len(policy["records"]) <= 1000
            or type(policy["expected_excluded_active_errors"]) is not int):
        raise ValueError("Invalid audited test-exclusion policy")
    result = {name: set() for name in KEYS}
    for record in policy["records"]:
        if (set(record) != {"dataset", "key", "evidence"} or record["dataset"] not in KEYS
                or not isinstance(record["evidence"], str) or not record["evidence"].strip()):
            raise ValueError("Each exact exclusion requires dataset, UUID and evidence")
        key = record["key"]
        if not isinstance(key, str) or str(UUID(key)) != key:
            raise ValueError("Exclusions must use canonical UUIDs, not patterns")
        if key in result[record["dataset"]]:
            raise ValueError("Duplicate exclusion")
        result[record["dataset"]].add(key)
    return result


def whole_holds(reason):
    return [{"table": name, "key": {}, "reason": reason} for name in NAMES]


def bounded_holds(issues, candidates):
    """Conservative recovery for missing-item orders with provable timestamps.

    Missing product identity holds every product on the affected date, rather
    than guessing a product. No timestamp/identity proof => whole-table hold.
    All other error classes continue to require ordinary owner-side repair.
    """
    active = [r for r in issues if r.get("active", True)]
    if not active:
        return [], set()
    if len(active) > 1000 or len(candidates) > 1000:
        return whole_holds("SCOPE_METADATA_LIMIT"), set()
    affected = {r.get("order_id") for r in active}
    if None in affected or any(r.get("error_code") != "MISSING_ORDER_ITEMS" for r in active):
        return whole_holds("UNRESOLVED_TRANSACTION_SCOPE"), affected - {None}
    hours, dates = set(), set()
    for order in affected:
        rows = [r for r in candidates if r.get("order_id") == order]
        orders = [r for r in rows if r.get("source_dataset") == "orders"]
        if not orders or any(not r.get("valid") for r in rows):
            return whole_holds("UNRESOLVED_TRANSACTION_SCOPE"), affected
        try:
            for row in rows:
                field = "ordered_at" if row["source_dataset"] == "orders" else "completed_at" if row["source_dataset"] == "payments" else None
                if field is None:
                    continue
                value = datetime.fromisoformat(row[field].replace("Z", "+00:00"))  # noqa: FURB162 - runtime Python 3.10
                if value.tzinfo is None:
                    raise ValueError("Unknown timezone")
                value = value.astimezone(ZoneInfo("Asia/Seoul"))
                hours.add(value.replace(minute=0, second=0, microsecond=0).isoformat())
                dates.add(value.date().isoformat())
        except (KeyError, TypeError, ValueError, AttributeError):
            return whole_holds("UNRESOLVED_TRANSACTION_SCOPE"), affected
    holds = [{"table": "order_sales_hourly", "key": {"hour_start_kst": hour},
              "reason": "UPSTREAM_ORDER_ITEMS_MISSING"} for hour in sorted(hours)]
    holds += [{"table": "product_sales_daily", "key": {"sales_date_kst": day},
               "reason": "UPSTREAM_ORDER_ITEMS_MISSING_DATE_WIDE"} for day in sorted(dates)]
    return holds, affected


def validate_source(source, previous, policy, root):
    uri = root + "/silver/runtime/trade/runs/" + source["run_id"] + "/manifest.json"
    if (source.get("engine") != "spark" or source.get("status") not in {"PASS", "INCOMPLETE"}
            or source.get("input_completeness") != "DECLARED_COMPLETE"
            or policy.get("source_run_id") != source["run_id"]
            or previous.get("silver_manifest") != uri
            or previous.get("status") not in {"PASS", "PARTIAL"}):
        raise ValueError("Recovery requires the same complete immutable Silver as the previous Gold")
    return uri


def read_uri(s3, uri):
    p = urlsplit(uri)
    if p.scheme != "s3" or not p.netloc or p.query or p.fragment or ".." in p.path.split("/"):
        raise ValueError("Expected a fixed S3 URI")
    result = s3.get_object(Bucket=p.netloc, Key=p.path.lstrip("/"))
    try:
        return result["Body"].read(), result["ETag"]
    finally:
        result["Body"].close()


def validate_publication(store, manifest):
    """Called by GoldPublisher before registering recovery partitions."""
    info = manifest["trade_recovery"]
    source_key = "silver/runtime/trade/runs/" + manifest["silver_run_id"] + "/manifest.json"
    raw, _ = store.get(source_key)
    done, _ = store.get("silver/runtime/trade/completed/" + manifest["silver_run_id"] + ".json")
    if (raw is None or done is None or digest(raw) != manifest["silver_manifest_sha256"]
            or json.loads(raw) != json.loads(done)
            or manifest["silver_manifest"] != store.uri(source_key)):
        raise ValueError("Recovery Silver lineage mismatch")
    policy_uri = info["policy_uri"]
    if not policy_uri.startswith(store.uri("pipelines/requests/trade-recovery/")):
        raise ValueError("Policy outside approved request prefix")
    policy_raw, _ = store.get(policy_uri[len(store.uri("")):])
    if policy_raw is None or digest(policy_raw) != info["policy_sha256"]:
        raise ValueError("Recovery policy hash mismatch")
    policy = json.loads(policy_raw)
    policy_keys(policy)
    if (policy["source_run_id"] != manifest["silver_run_id"]
            or info["excluded_active_error_count"] != policy["expected_excluded_active_errors"]):
        raise ValueError("Recovery exclusion evidence mismatch")


def merge_recovery_frames(fresh, old, holds, previous):
    from pyspark.sql import functions as F
    grains = {"order_sales_hourly": {"hour_start_kst"},
              "product_sales_daily": {"sales_date_kst", "article_id"}}
    merged = {}
    for name, frame in fresh.items():
        scopes = [r for r in holds if r["table"] == name]
        predicate = F.lit(False)
        for scope in scopes:
            if not set(scope["key"]) <= grains[name]:
                raise ValueError("Unknown hold key")
            match = F.lit(True)
            for field, value in scope["key"].items():
                match = match & (F.col(field).cast("string") == str(value))
            predicate = predicate | match
            available = bool(old[name].filter(match).limit(1).count())
            scope["previous_result_available"] = available
            scope["last_normal_result"] = (next((r.get("last_normal_result") for r in previous.get("held_scopes", [])
                if r["table"] == name and (not r["key"] or r["key"] == scope["key"])), None) if available else None)
        merged[name] = frame.filter(~predicate).unionByName(old[name].filter(predicate))
        if merged[name].groupBy(*sorted(grains[name])).count().filter("count > 1").limit(1).count():
            raise ValueError("Duplicate recovered metric key")
    spark = next(iter(fresh.values())).sparkSession
    rows = [(h["table"], json.dumps(h["key"], sort_keys=True), h["reason"], h["previous_result_available"],
             json.dumps(h["last_normal_result"], sort_keys=True) if h["last_normal_result"] else None) for h in holds]
    merged["refresh_holds"] = spark.createDataFrame(rows,
        "table_name string, key_json string, reason string, previous_result_available boolean, last_normal_result_json string")
    return merged


def execute(spark, config, s3):
    from pyspark.sql import functions as F

    from pipelines.spark_batch import (
        _spark_uri,
        _write_json,
        build_sales,
        configure_storage,
        save_tables,
    )

    if set(config) != {"job", "mode", "run_id", "output_root", "source_manifest", "source_sha256",
                       "policy_uri", "policy_sha256", "previous_gold_sha256"}:
        raise ValueError("Unknown recovery setting")
    if config["job"] != "trade" or config["mode"] != "audited_gold_recovery":
        raise ValueError("Only explicit audited trade recovery is supported")
    root = config["output_root"].rstrip("/")
    run = config["run_id"]
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run) or run == json.loads(read_uri(s3, config["source_manifest"])[0])["run_id"]:
        raise ValueError("Recovery must use a fresh run ID")
    raw, _ = read_uri(s3, config["source_manifest"])
    if digest(raw) != config["source_sha256"]:
        raise ValueError("Source changed")
    source = json.loads(raw)
    done = read_uri(s3, root + "/silver/runtime/trade/completed/" + source["run_id"] + ".json")[0]
    current_silver = read_uri(s3, root + "/silver/runtime/trade/current.json")[0]
    if json.loads(done) != source or digest(current_silver) != digest(raw):
        raise ValueError("Silver is not the current verified completed snapshot")
    old_raw, old_etag = read_uri(s3, root + "/gold_a/runtime/trade/current.json")
    if digest(old_raw) != config["previous_gold_sha256"]:
        raise ValueError("Previous Gold changed; re-audit")
    previous = json.loads(old_raw)
    policy_raw, _ = read_uri(s3, config["policy_uri"])
    if digest(policy_raw) != config["policy_sha256"]:
        raise ValueError("Policy changed")
    policy = json.loads(policy_raw)
    excluded = policy_keys(policy)
    validate_source(source, previous, policy, root)
    configure_storage(spark, root)
    tables = {name: spark.read.parquet(_spark_uri(source["outputs"][name])) for name in
              ["orders_current", "silver_order_items", "payment_attempts", "impact_candidates", "quarantined_records"]}
    predicate = F.lit(False)
    for dataset, ids in excluded.items():
        predicate = predicate | ((F.col("source_dataset") == dataset) & F.col("record_key").isin(sorted(ids)))
    predicate = F.coalesce(predicate, F.lit(False))
    issues = tables["quarantined_records"].filter(F.coalesce(F.col("active"), F.lit(True)))
    separated = issues.filter(predicate)
    excluded_count = separated.count()
    if excluded_count != policy["expected_excluded_active_errors"]:
        raise ValueError("Excluded error count differs from audited policy")
    remaining = issues.filter(~predicate).limit(1001).collect()
    remaining = [r.asDict() for r in remaining]
    ids = sorted({r.get("order_id") for r in remaining if r.get("order_id")})
    context = [r.asDict() for r in tables["impact_candidates"].filter(F.col("order_id").isin(ids)).limit(1001).collect()]
    holds, affected = bounded_holds(remaining, context)
    for name, dataset in [("orders_current", "orders"), ("silver_order_items", "order_items"), ("payment_attempts", "payments")]:
        tables[name] = tables[name].filter(~F.col(KEYS[dataset]).isin(sorted(excluded[dataset])))
        if affected:
            tables[name] = tables[name].filter(~F.col("order_id").isin(sorted(affected)))
        if any(not h["key"] for h in holds):
            tables[name] = tables[name].limit(0)
    products_uri = previous["products_manifest"]
    catalog = json.loads(read_uri(s3, products_uri)[0])
    if catalog["status"] != "PASS":
        raise ValueError("Product snapshot is not valid")
    products = {n: spark.read.parquet(_spark_uri(path)) for n, path in catalog["outputs"].items()}
    old = {n: spark.read.parquet(_spark_uri(previous["outputs"][n])) for n in NAMES}
    result = merge_recovery_frames(build_sales(tables, products), old, holds, previous)
    base = root + "/gold_a/runtime/trade/runs/" + run
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017 - runtime Python 3.10
    separated.write.mode("errorifexists").parquet(_spark_uri(base + "/audit/excluded_test_errors"))
    manifest = save_tables(result, base, run, now)
    manifest.update(status="PARTIAL" if holds else "PASS", silver_manifest=config["source_manifest"],
        silver_run_id=source["run_id"], silver_manifest_sha256=digest(raw), products_manifest=products_uri,
        previous_run_id=previous["run_id"], published_at=now, held_scopes=holds, held_context=context,
        check_version="gold-a.audited-recovery.v1", code_ref=config.get("code_ref", "audited-recovery"),
        trade_recovery={"policy_uri":config["policy_uri"], "policy_sha256":digest(policy_raw),
            "excluded_active_error_count":excluded_count, "remaining_active_error_count":len(remaining),
            "excluded_error_evidence":base + "/audit/excluded_test_errors", "original_silver_unchanged":True})
    _write_json(base + "/manifest.json", manifest)
    _write_json(root + "/gold_a/runtime/trade/completed/" + run + ".json", manifest)
    # Preserve the current pointer until the normal catalog publisher succeeds.
    _write_json(base + "/recovery-compare-and-swap.json", {"previous_gold_etag":old_etag,
        "source_sha256":digest(raw), "source_run_id":source["run_id"]})
    return manifest


def spark_self_check(spark):
    """Verify date-wide holds preserve only protected rows before any S3 write."""
    hourly = spark.createDataFrame([("h1", 2)], "hour_start_kst string, n long")
    fresh = {"order_sales_hourly": hourly, "product_sales_daily": spark.createDataFrame(
        [("2026-10-20", "a", 1), ("2026-10-20", "b", 1), ("2026-10-21", "a", 2)],
        "sales_date_kst string, article_id string, n long")}
    old = {"order_sales_hourly": hourly.limit(0), "product_sales_daily": spark.createDataFrame(
        [("2026-10-20", "a", 9), ("2026-10-20", "b", 8), ("2026-10-21", "a", 9)],
        "sales_date_kst string, article_id string, n long")}
    holds = [{"table": "product_sales_daily", "key": {"sales_date_kst": "2026-10-20"}, "reason": "TEST"}]
    result = merge_recovery_frames(fresh, old, holds, {"held_scopes": []})
    actual = {(r.sales_date_kst, r.article_id, r.n) for r in result["product_sales_daily"].collect()}
    if actual != {("2026-10-20", "a", 9), ("2026-10-20", "b", 8), ("2026-10-21", "a", 2)}:
        raise RuntimeError("Spark scoped merge self-check failed")
    if result["order_sales_hourly"].count() != 1 or result["refresh_holds"].count() != 1:
        raise RuntimeError("Spark unheld table/hold evidence self-check failed")


def main():
    import boto3
    from pyspark.sql import SparkSession

    from pipelines.runtime_control import trade_lease
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-uri", required=True)
    args = parser.parse_args()
    s3 = boto3.client("s3", region_name="ap-northeast-1")
    config = json.loads(read_uri(s3, args.config_uri)[0])
    spark = SparkSession.builder.appName("audited-trade-gold-recovery").getOrCreate()
    try:
        spark_self_check(spark)
        with trade_lease(config["output_root"], s3):
            result = execute(spark, config, s3)
        print(json.dumps({"run_id":result["run_id"], "status":result["status"], "counts":result["output_counts"]}))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
