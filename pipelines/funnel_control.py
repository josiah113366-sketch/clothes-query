"""Funnel checkpoint ownership, Athena verification and next bounded request."""
import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

from pipelines.funnel_demo import encode, read_bytes
from pipelines.funnel_incremental import VERSION, fixed_json, plan_batch, validate

CONTROL = "silver/runtime/clicks/catalog-control/incremental.json"


class LocalStore:
    """Local integration adapter; exclusive lock protects compare-and-swap."""
    def __init__(self, root):
        self.root = Path(root)

    def get(self, name):
        path = self.root / name
        if not path.exists():
            return None, None
        raw = path.read_bytes()
        return raw, hashlib.sha256(raw).hexdigest()

    def put(self, name, body, etag=None):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = target.with_suffix(".lock")
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            _, actual = self.get(name)
            if actual != etag:
                raise ValueError("처리 위치가 다른 실행에 의해 변경됐습니다")
            pending = target.with_suffix(".pending")
            pending.write_bytes(body)
            os.replace(pending, target)
            return hashlib.sha256(body).hexdigest()
        finally:
            os.close(handle)
            lock.unlink()


def store_for(root):
    if root.startswith("s3://"):
        import boto3

        from pipelines.r6_publication import S3Store
        return S3Store(root, boto3.client("s3", region_name="ap-northeast-1"))
    return LocalStore(root)


def immutable_json(root, key, value):
    store = store_for(root)
    raw, _ = store.get(key)
    body = encode(value)
    if raw is not None:
        if raw != body:
            raise ValueError("같은 요청·입력 ID의 내용을 덮어쓰지 않습니다")
    else:
        store.put(key, body)
    return root.rstrip("/") + "/" + key


def acquire(store, config):
    raw, etag = store.get(CONTROL)
    state = json.loads(raw) if raw else {"tip": None, "owner": None}
    if state.get("owner") not in {None, config["run_id"]} or state["tip"] != config["previous"]:
        raise ValueError("다른 실행이 진행 중이거나 처리 기준이 오래됐습니다")
    state["owner"] = config["run_id"]
    store.put(CONTROL, encode(state), etag)


def release(store, run_id):
    raw, etag = store.get(CONTROL)
    state = json.loads(raw) if raw else {}
    if state.get("owner") != run_id:
        raise ValueError("처리 위치 잠금 소유자가 다릅니다")
    state["owner"] = None
    store.put(CONTROL, encode(state), etag)


def advance(store, config, manifest_uri, digest, query_id):
    raw, etag = store.get(CONTROL)
    state = json.loads(raw) if raw else {}
    tip = {"uri": manifest_uri, "sha256": digest}
    if state.get("tip") == tip and state.get("owner") is None:
        return  # same immutable run, already acknowledged
    if state.get("owner") != config["run_id"] or state.get("tip") != config["previous"]:
        raise ValueError("확인한 실행과 처리 위치 잠금이 다릅니다")
    state.update(tip=tip, owner=None, athena_query_id=query_id)
    store.put(CONTROL, encode(state), etag)


def verify_athena(client, database, workgroup, output, run_id, counts, timeout=240, sleep=time.sleep):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", database) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("조회 DB·실행 ID가 올바르지 않습니다")
    if not workgroup or not output.startswith("s3://"):
        raise ValueError("퍼널 조회 검증용 Athena workgroup·결과 S3 위치가 필요합니다")
    names = ("funnel_session_product", "funnel_daily", "refresh_holds")
    sql = " UNION ALL ".join(
        f"SELECT '{name}' AS metric, count(*) AS n FROM {database}.{name}_runs "
        f"WHERE run_id = '{run_id}'" + (" AND channel = 'funnels'" if name == "refresh_holds" else "")
        for name in names)
    query_id = client.start_query_execution(QueryString=sql, WorkGroup=workgroup,
        QueryExecutionContext={"Database": database}, ResultConfiguration={"OutputLocation": output})["QueryExecutionId"]
    deadline = time.monotonic() + timeout
    while True:
        status = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]["State"]
        if status == "SUCCEEDED":
            break
        if status in {"FAILED", "CANCELLED"}:
            raise RuntimeError("Athena 고정 실행 조회 검증이 실패했습니다; 처리 위치를 유지합니다")
        if time.monotonic() >= deadline:
            client.stop_query_execution(QueryExecutionId=query_id)
            raise TimeoutError("Athena 검증 시간 초과; 처리 위치를 유지합니다")
        sleep(2)
    rows = client.get_query_results(QueryExecutionId=query_id, MaxResults=10)["ResultSet"]["Rows"][1:]
    actual = {row["Data"][0]["VarCharValue"]: int(row["Data"][1]["VarCharValue"]) for row in rows}
    if actual != {name: counts[name] for name in names}:
        raise ValueError("Athena 조회와 저장된 지표·보류 건수가 다릅니다; 처리 위치를 유지합니다")
    return query_id


def acknowledge(config, database, workgroup, output):
    """Called only after the ordinary Gold publisher registered this same run."""
    import boto3
    root = validate(config)
    uri = root + "/gold_a/runtime/funnels/runs/" + config["run_id"] + "/manifest.json"
    raw = read_bytes(uri)
    manifest = json.loads(raw)
    if manifest.get("version") != VERSION or manifest.get("run_id") != config["run_id"]:
        raise ValueError("증분 완료 결과가 다릅니다")
    query_id = verify_athena(boto3.client("athena", region_name="ap-northeast-1"), database, workgroup,
                             output, config["run_id"], manifest["output_counts"])
    store = store_for(root)
    checkpoint, _ = store.get(CONTROL)
    state = json.loads(checkpoint) if checkpoint else {}
    tip = {"uri": uri, "sha256": hashlib.sha256(raw).hexdigest()}
    if not ((state.get("owner") == config["run_id"] and state.get("tip") == config["previous"])
            or (state.get("owner") is None and state.get("tip") == tip)):
        raise ValueError("오래된 공개 재시도는 최신 결과를 교체할 수 없습니다")
    if manifest["batch"]["remaining_files"] == 0:
        # Keep legacy pointer readers aligned, under the same incremental lease.
        # Athena readers still use gold_runs, never these JSON pointers.
        from pipelines.spark_batch import _write_json
        _write_json(root + "/gold_a/runtime/funnels/current.json", manifest)
        _write_json(root + "/silver/runtime/clicks/current.json", json.loads(read_bytes(manifest["silver_clicks_manifest"])))
    advance(store, config, uri, tip["sha256"], query_id)
    return {"status": "ATHENA_VERIFIED", "run_id": config["run_id"], "query_id": query_id}


def next_request(config):
    """Replan the same captured inventory after an acknowledged batch."""
    root = validate(config)
    raw, _ = store_for(root).get(CONTROL)
    state = json.loads(raw) if raw else {}
    if state.get("owner") or not state.get("tip"):
        raise ValueError("조회 검증과 처리 위치 확정 후에만 다음 묶음을 준비합니다")
    prior = fixed_json(state["tip"])
    if prior["run_id"] != config["run_id"] or prior["inventory"] != config["inventory"]:
        raise ValueError("다음 묶음을 요청한 실행이 현재 처리 위치와 다릅니다")
    plan = plan_batch(fixed_json(config["inventory"])["objects"], prior["processed"],
                      config["max_files"], config["max_bytes"])
    if not plan["objects"]:
        return {"continue": False, "config_uri": "", "next_run_id": ""}
    token = hashlib.sha256(encode({"previous": state["tip"], "objects": plan["objects"]})).hexdigest()[:24]
    run_id = "funnels-inc-" + token
    request = {**config, "run_id": run_id, "previous": state["tip"], "catalog": prior["catalog"]}
    uri = immutable_json(root, "pipelines/requests/funnels-incremental/" + run_id + ".json", request)
    return {"continue": True, "config_uri": uri, "next_run_id": run_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-uri", required=True)
    parser.add_argument("--result-file", default="/dev/termination-log")
    parser.add_argument("--release-stopped-owner")
    parser.add_argument("--confirm-driver-stopped", action="store_true")
    args = parser.parse_args()
    config = json.loads(read_bytes(args.config_uri))
    if args.release_stopped_owner:
        if not args.confirm_driver_stopped or args.release_stopped_owner != config.get("run_id"):
            raise ValueError("Driver 종료 확인과 정확한 기존 실행 소유자가 필요합니다")
        release(store_for(validate(config)), args.release_stopped_owner)
        print(encode({"status": "LEASE_RELEASED", "run_id": args.release_stopped_owner}).decode())
        return
    result = next_request(config) if config.get("mode") == "incremental" else {
        "continue": False, "config_uri": "", "next_run_id": ""}
    target = Path(args.result_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode(result))


if __name__ == "__main__":
    main()
