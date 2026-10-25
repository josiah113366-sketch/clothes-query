"""고정 세션 시연 전용 실행기. 운영 Silver/R6/Gold 공개 참조를 변경하지 않는다."""
import argparse
import hashlib
import json
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "funnel-demo.v1"


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def read_bytes(uri, s3=None):
    if set(uri.replace("\\", "/").split("/")) & {"ground_truth", "reviews_truth"}:
        raise ValueError("시연 입력으로 평가용 정답표를 사용할 수 없습니다")
    if uri.startswith("s3://"):
        if s3 is None:
            import boto3
            s3 = boto3.client("s3", region_name="ap-northeast-1")
        parsed = urlsplit(uri)
        response = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()
    if "://" in uri:
        raise ValueError("시연 입력은 S3 또는 로컬 경로여야 합니다")
    return Path(uri).read_bytes()


def relative_uri(base, name):
    if not isinstance(name, str) or name.startswith("/") or "\\" in name or any(p in {"", ".", ".."} for p in name.split("/")):
        raise ValueError("시연 파일은 manifest 아래 상대 경로여야 합니다")
    return base.rsplit("/", 1)[0] + "/" + name


def validate_request(config):
    fields = {"job", "mode", "run_id", "output_root", "selection_manifest", "selection_sha256"}
    if not isinstance(config, dict) or set(config) != fields or config["job"] != "funnels" or config["mode"] != "demo":
        raise ValueError("시연 전용 퍼널 요청이 필요합니다")
    if not isinstance(config["run_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config["run_id"]):
        raise ValueError("시연 run_id가 올바르지 않습니다")
    if not isinstance(config["selection_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", config["selection_sha256"]):
        raise ValueError("고정 입력 manifest 해시가 필요합니다")
    root, manifest = config["output_root"], config["selection_manifest"]
    if not isinstance(root, str) or not isinstance(manifest, str) or not root or not manifest:
        raise ValueError("시연 입력·출력 경로가 필요합니다")
    if root.startswith("s3://"):
        parsed = urlsplit(root)
        if (not parsed.netloc or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") != "/pipelines/demo/funnels"):
            raise ValueError("S3 시연 출력은 pipelines/demo/funnels 전용 경로여야 합니다")
        if not manifest.startswith("s3://"):
            raise ValueError("S3 시연에는 S3 고정 입력이 필요합니다")
    elif "://" in root or "://" in manifest:
        raise ValueError("로컬 시연에는 로컬 입력이 필요합니다")
    else:
        target, source = Path(root).resolve(), Path(manifest).resolve()
        if target == source or target in source.parents:
            raise ValueError("시연 출력은 입력을 포함할 수 없습니다")
    return root.rstrip("/") + "/runs/" + config["run_id"]


def load_selection(config, s3=None):
    validate_request(config)
    raw = read_bytes(config["selection_manifest"], s3)
    if hashlib.sha256(raw).hexdigest() != config["selection_sha256"]:
        raise ValueError("선택 입력 manifest가 변경됐습니다")
    manifest = json.loads(raw)
    sessions = manifest.get("session_ids", [])
    if (manifest.get("version") != VERSION or manifest.get("coverage_status") != "FIXED_SOURCE_INVENTORY_COMPLETE"
            or not sessions or len(sessions) > 500 or len(set(sessions)) != len(sessions)
            or any(not isinstance(s, str) or not s.strip() for s in sessions)
            or manifest.get("selected_order_quality") != "PASS"):
        raise ValueError("고정 세션 범위·품질 계약이 다릅니다")
    source = manifest["source_trade"]
    source_raw = read_bytes(source["manifest"], s3)
    if hashlib.sha256(source_raw).hexdigest() != source["sha256"]:
        raise ValueError("기준 거래 manifest가 변경됐습니다")
    original = json.loads(source_raw)
    if original["run_id"] != source["run_id"] or original["status"] != source["quality_status"]:
        raise ValueError("원본 거래 실행·품질 참조가 다릅니다")
    paths = {}
    required = {"clicks", "orders", "items", "payments", "checks", "order_quality", "designs", "variants", "expected"}
    if set(manifest.get("objects", {})) != required:
        raise ValueError("고정 선택 입력이 빠져 있습니다")
    for name, item in manifest["objects"].items():
        uri = relative_uri(config["selection_manifest"], item["file"])
        body = read_bytes(uri, s3)
        if len(body) != item["size"] or hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("고정 선택 파일이 변경됐습니다: " + name)
        paths[name] = uri
    return manifest, paths


class Measurements:
    def __init__(self, clock=time.monotonic):
        self.clock, self.started, self.stages = clock, clock(), []

    @contextmanager
    def stage(self, name):
        started = self.clock()
        row = {"stage": name, "status": "FAILED"}
        try:
            yield
            row["status"] = "SUCCESS"
        finally:
            row.update(seconds=round(self.clock() - started, 6), cumulative_seconds=round(self.clock() - self.started, 6))
            self.stages.append(row)


def verify_complete(config):
    base = validate_request(config)
    manifest = json.loads(read_bytes(base + "/manifest.json"))
    completed = json.loads(read_bytes(base + "/completed.json"))
    if (completed != manifest or manifest.get("run_id") != config["run_id"] or manifest.get("status") != "PASS"
            or manifest.get("selection_sha256") != config["selection_sha256"]
            or manifest.get("publishable_as_full_snapshot") is not False):
        raise ValueError("시연 완료 결과가 요청과 다릅니다")
    return {"status": "DEMO_VERIFIED", "run_id": config["run_id"], "production_published": False}


def execute(spark, config):
    from pyspark.sql import functions as F

    from pipelines.gold_a.funnels import build_funnels_spark
    from pipelines.silver.clicks import build_clicks_spark
    from pipelines.spark_batch import (
        SCHEMAS,
        _spark_uri,
        _write_json,
        build_catalog,
        configure_storage,
        read_source,
        save_tables,
    )

    base = validate_request(config)
    if base.startswith("s3://"):
        import boto3
        parsed = urlsplit(base)
        occupied = boto3.client("s3").list_objects_v2(Bucket=parsed.netloc, Prefix=parsed.path.lstrip("/") + "/", MaxKeys=1).get("Contents")
    else:
        occupied = Path(base).exists()
    if occupied:
        raise ValueError("기존 시연 결과를 덮어쓰지 않습니다")
    timer, clicks, catalog = Measurements(), None, None
    result = {"run_id": config["run_id"], "status": "FAILED", "publishable_as_full_snapshot": False,
              "production_published": False, "selection_sha256": config["selection_sha256"]}
    try:
        with timer.stage("input_validation"):
            manifest, paths = load_selection(config)
        configure_storage(spark, base)
        checked = datetime.now(timezone.utc).isoformat()
        with timer.stage("click_silver_and_save"):
            clicks = build_clicks_spark(spark, [_spark_uri(paths["clicks"])])
            if clicks["quarantined_records"].limit(1).count():
                raise ValueError("선택 클릭의 품질이 불완전합니다")
            saved_clicks = save_tables(clicks, base + "/silver_clicks", config["run_id"], checked)
            events = clicks["click_events"]
            if events.filter(~F.col("session_id").isin(manifest["session_ids"])).limit(1).count():
                raise ValueError("선택 밖 세션이 입력에 섞였습니다")
        with timer.stage("trade_and_catalog"):
            trade = {table: spark.read.schema(SCHEMAS[table]).json(_spark_uri(paths[name])) for table, name in
                     (("orders_current", "orders"), ("silver_order_items", "items"), ("payment_attempts", "payments"),
                      ("order_amount_checks", "checks"), ("dq_order_results", "order_quality"))}
            orders = trade["orders_current"]
            if orders.filter(~F.col("session_id").isin(manifest["session_ids"])).limit(1).count():
                raise ValueError("선택 밖 주문이 입력에 섞였습니다")
            checks = trade["order_amount_checks"]
            if (checks.filter("status != 'PASS' OR status IS NULL").limit(1).count()
                    or orders.select("order_id").join(checks.select("order_id"), "order_id", "left_anti").limit(1).count()
                    or trade["dq_order_results"].filter("active_error_count > 0").limit(1).count()):
                raise ValueError("선택 주문의 검사·품질이 불완전합니다")
            raw = read_source(spark, "product_design", [_spark_uri(paths["designs"])]).unionByName(
                read_source(spark, "product_variant", [_spark_uri(paths["variants"])]))
            catalog = build_catalog(raw)
            saved_products = save_tables(catalog, base + "/products", config["run_id"], checked)
        with timer.stage("funnel_calculation_and_save"):
            gold = build_funnels_spark(clicks, trade, catalog, _scoped=True)
            saved_gold = save_tables(gold, base + "/gold", config["run_id"], checked)
        with timer.stage("result_verification"):
            expected = json.loads(read_bytes(paths["expected"]))
            for name, uri in saved_gold["outputs"].items():
                frame = spark.read.parquet(_spark_uri(uri))
                if frame.count() > 50000:
                    raise ValueError("시연 결과 검수 한도 50,000행을 초과했습니다")
                actual = sorted([encode(row.asDict()).decode() for row in frame.collect()])
                if actual != sorted(encode(row).decode() for row in expected[name]):
                    raise ValueError("퍼널 결과가 독립 기대값과 다릅니다")
            load_selection(config)  # 저장 중 고정 입력이 바뀌었으면 완료를 공개하지 않는다.
        result.update(status="PASS", coverage_status=manifest["coverage_status"],
                      source_trade=manifest["source_trade"], session_count=len(manifest["session_ids"]),
                      counts=manifest["counts"], output_counts=saved_gold["output_counts"],
                      gold=saved_gold, clicks=saved_clicks, products=saved_products,
                      preparation_metrics=manifest["preparation_metrics"])
    finally:
        for tables in (clicks, catalog):
            for cache in (tables or {}).get("_cache", ()):
                cache.unpersist()
        result["measurements"] = {"stages": timer.stages, "total_seconds": round(timer.clock() - timer.started, 6),
            "measurement_scope": "after-SparkSession; excludes submission/pod wait and final JSON writes",
            "spark_version": spark.version, "python_version": sys.version.split()[0], "master": spark.sparkContext.master,
            "application_id": spark.sparkContext.applicationId, "executor_pod_peak_memory_bytes": None,
            "driver_pod_peak_memory_bytes": None, "pod_resource_metrics_status": "NOT_COLLECTED",
            "driver_pod_cpu_millicores_max": None, "executor_pod_cpu_millicores_max": None,
            "spark_conf": {key: spark.sparkContext.getConf().get(key, "unset") for key in
                           ("spark.executor.memory", "spark.executor.cores", "spark.sql.shuffle.partitions", "spark.default.parallelism")}}
        if "counts" in result:
            seconds = next(row["seconds"] for row in timer.stages if row["stage"] == "click_silver_and_save")
            result["measurements"]["click_input_rows_per_second"] = result["counts"]["clicks"] / seconds if seconds else None
            result["measurements"]["selected_input_bytes"] = sum(item["size"] for name, item in manifest["objects"].items() if name != "expected")
        _write_json(base + "/metrics.json", result)
    _write_json(base + "/manifest.json", result)
    _write_json(base + "/completed.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-uri", required=True)
    parser.add_argument("--expected-job", choices=("funnels",), default="funnels")
    args = parser.parse_args()
    config = json.loads(read_bytes(args.config_uri))
    validate_request(config)
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.appName("silver-gold-a-funnel-demo").getOrCreate()
    try:
        result = execute(spark, config)
        print(encode({k: result[k] for k in ("run_id", "status", "output_counts", "measurements")}).decode())
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
