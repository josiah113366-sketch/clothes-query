"""승인된 Silver 요청의 입력을 고정하고 주문별 상태를 병합한다. RDS를 수정하지 않는다."""
import argparse
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.format_rules import FormatRules
from pipelines.r6_publication import S3Store, encode, millis
from pipelines.timestamps import parse_iso_datetime


def read_json(uri, s3=None):
    if uri.startswith("s3://"):
        parsed = urlsplit(uri)
        response = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
        try:
            raw = response["Body"].read()
        finally:
            response["Body"].close()
    else:
        from pathlib import Path
        raw = Path(uri).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate_request(request):
    allowed = {"request_id", "window_start", "window_end", "order_ids", "rule_version", "attempt", "parent_request_id", "source", "anomaly_id", "report_id"}
    if set(request) - allowed or request.get("source", "SILVER") != "SILVER":
        raise ValueError("Silver 승인 요청 필드 오류")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request.get("request_id", "")):
        raise ValueError("request_id 형식 오류")
    start, end = [approval_time(request[key]) for key in ("window_start", "window_end")]
    if end <= start:
        raise ValueError("승인 범위는 UTC 시작 포함·끝 제외 구간이어야 합니다")
    if request.get("rule_version") != FormatRules().version:
        raise ValueError("승인 규칙 버전과 실행 규칙이 다릅니다")
    ids = request.get("order_ids", [])
    if not isinstance(ids, list) or len(ids) > 500 or any(not isinstance(v, str) or not v.strip() for v in ids):
        raise ValueError("order_ids는 최대 500개의 주문 번호 목록입니다")
    attempt = request.get("attempt", 1)
    if type(attempt) is not int or not 1 <= attempt <= 100:
        raise ValueError("재처리 attempt는 1~100입니다")
    return start, end


def approval_time(value):
    # 기존 승인 화면의 YYYY-MM-DD HH:MM:SS는 UTC다. 원천 업무 시각 정책과는 별도다.
    parsed = parse_iso_datetime(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def prepare(request, runtime, s3):
    """운영 입력 경로는 DAG 환경 설정에서만 받는다. 승인 화면은 원본 목록을 보내지 않는다."""
    validate_request(request)
    root = runtime["output_root"]
    store = S3Store(root, s3)
    request_id = request["request_id"]
    attempt = request.get("attempt", 1)
    run_id = f"reprocess-{request_id}-{attempt}"
    config_key = f"pipelines/requests/reprocess/{request_id}-{attempt}.json"
    manifest_key = f"pipelines/input-manifests/reprocess/{request_id}-{attempt}.json"
    prior, _ = store.get(config_key)
    if prior:
        config = json.loads(prior)
        fixed, _ = store.get(manifest_key)
        if not fixed or json.loads(fixed).get("request") != request:
            raise ValueError("이미 고정한 재처리 요청 내용과 다릅니다")
        record_started(request, store, store.uri(manifest_key))
        return store.uri(config_key)
    names = {"orders", "order_items", "payments", "designs", "variants"}
    if set(runtime.get("inputs", {})) != names:
        raise ValueError("재처리 전체 이력과 상품 기준정보 경로가 필요합니다")
    paths, objects = {}, []
    for name, locations in runtime["inputs"].items():
        paths[name] = []
        for uri in locations:
            parsed = urlsplit(uri)
            key = parsed.path.lstrip("/")
            if parsed.scheme != "s3" or not key:
                raise ValueError("재처리 입력은 데이터셋별 S3 경로여야 합니다")
            if name in {"orders", "order_items", "payments"} and not key.startswith("bronze_v2/"):
                raise ValueError("시간대 재처리는 Kafka 위치가 있는 bronze_v2를 사용합니다")
            entries = (item for page in s3.get_paginator("list_objects_v2").paginate(Bucket=parsed.netloc, Prefix=key)
                       for item in page.get("Contents", [])) if uri.endswith("/") else [
                           {"Key": key, **s3.head_object(Bucket=parsed.netloc, Key=key)}]
            for item in entries:
                if not item["Key"].endswith((".json", ".jsonl", ".parquet")):
                    continue
                object_uri = "s3://" + parsed.netloc + "/" + item["Key"]
                paths[name].append(object_uri)
                objects.append({"dataset": name, "uri": object_uri, "etag": item["ETag"],
                                "size": item.get("Size", item.get("ContentLength"))})
        if not paths[name]:
            raise ValueError("재처리 원본 파일 없음: " + name)
        paths[name] = sorted(set(paths[name]))
    if (len(objects) > 10000 or len({v["uri"] for v in objects}) != len(objects)
            or any(v["size"] > 64 * 1024 * 1024 for v in objects)):
        raise ValueError("중복 입력 또는 10,000개 객체 한도 초과")
    previous_uri = store.uri("silver/runtime/trade/current.json")
    previous, _ = read_json(previous_uri, s3)
    fixed_uri = store.uri(f"silver/runtime/trade/runs/{previous['run_id']}/manifest.json")
    fixed, digest = read_json(fixed_uri, s3)
    if fixed != previous or "dq_order_results" not in fixed.get("outputs", {}):
        raise ValueError("부분 재처리 전에 새 버전의 정상 거래 배치를 한 번 완료해야 합니다")
    gold, _ = read_json(store.uri("gold_a/runtime/trade/current.json"), s3)
    if gold.get("silver_manifest") != fixed_uri:
        raise ValueError("Silver와 Gold A의 기준 실행이 다릅니다")
    manifest = {"request": request, "objects": sorted(objects, key=lambda v: (v["dataset"], v["uri"])),
                "previous_silver": fixed_uri, "previous_sha256": digest,
                "previous_gold_run_id": gold["run_id"], "status": "FIXED"}
    config = {"job": "trade", "run_id": run_id, "input_complete": True, "output_root": root,
              "inputs": paths, "input_manifest": store.uri(manifest_key),
              "reprocess_scope": {**request, "previous_silver": fixed_uri, "previous_sha256": digest,
                                  "previous_gold_run_id": gold["run_id"]}}
    store.immutable(manifest_key, encode(manifest))
    store.immutable(config_key, encode(config))
    record_started(request, store, store.uri(manifest_key))
    return store.uri(config_key)


def verify_fixed_inputs(uri, inventory):
    import boto3
    manifest, _ = read_json(uri, boto3.client("s3", region_name="ap-northeast-1") if uri.startswith("s3://") else None)
    expected = sorted(manifest["objects"], key=lambda v: (v["dataset"], v["uri"]))
    actual = sorted(inventory, key=lambda v: (v["dataset"], v["uri"]))
    if expected != actual:
        raise ValueError("재처리 입력 객체·ETag가 고정 manifest와 다릅니다")


def merge_scoped_silver(spark, fresh, scope, root, inventory):
    """대상 주문 상태만 바꾸고 대상 밖 상태를 이전 불변 실행에서 보존한다."""
    import boto3
    from pyspark.sql import functions as F

    from pipelines.spark_batch import DQ_METRICS, _spark_uri
    s3 = boto3.client("s3", region_name="ap-northeast-1") if root.startswith("s3://") else None
    previous, digest = read_json(scope["previous_silver"], s3)
    if digest != scope["previous_sha256"]:
        raise ValueError("이전 Silver 고정 manifest가 변경됐습니다")
    current, _ = read_json(root.rstrip("/") + "/silver/runtime/trade/current.json", s3)
    gold, _ = read_json(root.rstrip("/") + "/gold_a/runtime/trade/current.json", s3)
    if current["run_id"] != previous["run_id"] or gold["run_id"] != scope["previous_gold_run_id"]:
        raise ValueError("재처리 준비 후 기준 실행이 변경됐습니다. 새 요청으로 입력을 다시 고정하세요")
    if scope["previous_silver"].rstrip("/") != root.rstrip("/") + "/silver/runtime/trade/runs/" + previous["run_id"] + "/manifest.json":
        raise ValueError("이전 Silver가 같은 출력 root의 고정 실행이 아닙니다")
    old_products = {v["uri"]: (v.get("etag"), v.get("mtime_ns"), v["size"])
                    for v in previous["input_objects"] if v["dataset"] in {"designs", "variants"}}
    new_products = {v["uri"]: (v.get("etag"), v.get("mtime_ns"), v["size"])
                    for v in inventory if v["dataset"] in {"designs", "variants"}}
    if old_products != new_products:
        raise ValueError("부분 재처리 중 상품 기준정보 변경은 허용하지 않습니다. 전체 정상 배치를 먼저 실행하세요")
    ids = set(scope.get("order_ids", []))
    candidates = fresh["impact_candidates"]
    if not ids:
        raw = fresh["_cache"][0]
        stamp = F.to_timestamp(F.get_json_object("raw", "$.kafka_timestamp"))
        affected = raw.filter((stamp >= F.to_timestamp(F.lit(scope["window_start"]))) &
                              (stamp < F.to_timestamp(F.lit(scope["window_end"]))))
        if affected.filter(F.col("order_id").isNull()).limit(1).count():
            raise ValueError("승인 시간대에 주문을 식별할 수 없는 원본이 있습니다")
        ids = {r.order_id for r in affected.select("order_id").distinct().limit(501).collect()}
    if not ids or len(ids) > 500:
        raise ValueError("부분 재처리 대상은 1~500개 주문이어야 합니다")
    available = {r.order_id for r in candidates.filter(F.col("order_id").isin(sorted(ids))).select("order_id").distinct().collect()}
    if available != ids:
        raise ValueError("요청 주문의 원본 이력이 없으므로 삭제된 상태로 처리하지 않습니다")
    old_candidates = spark.read.parquet(_spark_uri(previous["outputs"]["impact_candidates"]))
    # 결제가 다른 주문으로 이동한 경우 이전 주문도 함께 다시 계산한다.
    connected = candidates.unionByName(old_candidates, allowMissingColumns=True)
    while True:
        payments = connected.filter(F.col("order_id").isin(sorted(ids))).select("payment_id").where("payment_id is not null").distinct()
        related = connected.join(payments, "payment_id").select("order_id").where("order_id is not null").distinct()
        expanded = ids | {r.order_id for r in related.limit(501).collect()}
        if len(expanded) > 500:
            raise ValueError("연결 주문까지 포함한 재처리 대상이 500개를 초과했습니다")
        if expanded == ids:
            break
        ids = expanded
    if fresh["quarantined_records"].filter(F.col("order_id").isNull()).limit(1).count():
        raise ValueError("주문을 식별할 수 없는 오류가 있어 부분 교체를 중단합니다")
    for name in list(fresh):
        if name.startswith("_") or name == "dq_results":
            continue
        if name not in previous["outputs"]:
            raise ValueError("이전 Silver에 부분 병합용 결과가 없습니다: " + name)
        old = spark.read.parquet(_spark_uri(previous["outputs"][name]))
        selected = fresh[name].filter(F.col("order_id").isin(sorted(ids)))
        # 이전의 6자리 UTC TIMESTAMP와 새 계산의 문자열 타입을 명시적으로 맞춘다.
        for field in old.schema.fields:
            if field.name in selected.columns:
                selected = selected.withColumn(field.name, F.col(field.name).cast(field.dataType))
        fresh[name] = old.filter(~F.col("order_id").isin(sorted(ids)) | F.col("order_id").isNull()).unionByName(
            selected, allowMissingColumns=True)
    summary = fresh["dq_order_results"].groupBy("source_dataset").agg(*[F.sum(key).alias(key) for key in DQ_METRICS])
    fresh["dq_results"] = summary.withColumn("status", F.when(F.col("active_error_count") > 0, "INCOMPLETE").otherwise("PASS")).withColumn(
        "check_version", F.lit("transactions.v9")).withColumn("format_rules", F.lit(json.dumps(FormatRules().reference())))
    return fresh, {"kind": "ORDER_STATE_PATCH", "order_ids": sorted(ids), "window_start": scope["window_start"],
                   "window_end": scope["window_end"], "previous_silver_run_id": previous["run_id"]}


EVENT_SCHEMA = pa.schema([(key, pa.timestamp("ms") if key in {"at", "window_start", "window_end"} else
                           pa.int32() if key == "attempt" else pa.string()) for key in (
    "request_id", "step", "at", "actor", "reason", "window_start", "window_end", "rule_version", "source",
    "attempt", "parent_request_id", "detail")])


def record_started(request, store, manifest_uri):
    key = f"gold_b/reprocess_events/silver-{request['request_id']}-{request.get('attempt', 1)}-started.parquet"
    old, _ = store.get(key)
    if old:
        return
    row = {"request_id": request["request_id"], "step": "STARTED", "at": millis(datetime.now(timezone.utc)),
           "actor": "silver_gold_a_reprocess", "reason": "승인된 주문의 원본 입력 고정 완료",
           "window_start": millis(approval_time(request["window_start"])),
           "window_end": millis(approval_time(request["window_end"])), "rule_version": request["rule_version"],
           "source": "SILVER", "attempt": request.get("attempt", 1), "parent_request_id": request.get("parent_request_id"),
           "detail": encode({"input_manifest": manifest_uri}).decode()}
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([row], schema=EVENT_SCHEMA), output)
    store.put(key, output.getvalue())


def record_result(request, root, s3):
    validate_request(request)
    store = S3Store(root, s3)
    run_id = f"reprocess-{request['request_id']}-{request.get('attempt', 1)}"
    silver, _ = store.get(f"silver/runtime/trade/completed/{run_id}.json")
    gold, _ = store.get(f"gold_a/runtime/trade/completed/{run_id}.json")
    r6, _ = store.get(f"silver/runtime/trade/catalog/completed/{run_id}.parquet")
    public, _ = store.get(f"gold_a/runtime/trade/catalog/completed/{run_id}.parquet")
    status, step = "FAILED", "FAILED"
    detail = {"status": status, "silver_run_id": run_id if silver else None, "actual_scope": None,
              "held_scopes": [], "failure_reason": "PROCESSING_OR_PUBLICATION_INCOMPLETE"}
    if silver and gold and r6 and public:
        sm, gm = json.loads(silver), json.loads(gold)
        if sm.get("run_id") != run_id or gm.get("run_id") != run_id:
            raise ValueError("재처리 완료 실행 ID가 다릅니다")
        held = gm.get("held_scopes", [])
        status = "PARTIAL" if held else "SUCCESS"
        step = "LEDGER_REPLACED"
        detail.update(status=status, actual_scope=sm.get("actual_scope"),
                      held_scopes=held[:20], failure_reason=None,
                      silver_manifest=store.uri(f"silver/runtime/trade/runs/{run_id}/manifest.json"),
                      gold_manifest=store.uri(f"gold_a/runtime/trade/runs/{run_id}/manifest.json"))
        if len(encode(detail)) > 16000:
            detail["held_scopes"] = [{"manifest_ref": detail["gold_manifest"]}] if held else []
            detail["actual_scope"] = {"manifest_ref": detail["silver_manifest"]}
    row = {"request_id": request["request_id"], "step": step, "at": millis(datetime.now(timezone.utc)),
           "actor": "silver_gold_a_reprocess", "reason": "Silver 주문 상태 부분 재처리 결과",
           "window_start": millis(approval_time(request["window_start"])), "window_end": millis(approval_time(request["window_end"])),
           "rule_version": request["rule_version"], "source": "SILVER", "attempt": request.get("attempt", 1),
           "parent_request_id": request.get("parent_request_id"), "detail": encode(detail).decode()}
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([row], schema=EVENT_SCHEMA), output)
    # 단계는 추가만 한다. 정상 실행을 FAILED로 되돌리거나 기존 Gold B 파일을 수정하지 않는다.
    store.put("gold_b/reprocess_events/silver-" + uuid4().hex + ".parquet", output.getvalue())
    if status == "FAILED":
        raise RuntimeError("Silver 재처리 또는 공개 미완료; FAILED 기록을 남겼습니다")
    return detail


def main():
    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--runtime-json", required=True)
    args = parser.parse_args()
    request, runtime = json.loads(args.request_json), json.loads(args.runtime_json)
    s3 = boto3.client("s3", region_name="ap-northeast-1")
    if args.action == "prepare":
        print(encode({"config_uri": prepare(request, runtime, s3)}).decode())
    else:
        result = record_result(request, runtime["output_root"], s3)
        print(encode({"status": result["status"], "silver_run_id": result["silver_run_id"]}).decode())


if __name__ == "__main__":
    main()
