"""Capture current inputs and prepare one bounded manual funnel request.

Default writes local JSON only. --write-s3 explicitly stores requests/manifests
under the existing pipelines prefixes; it does not launch a DAG.
"""
import argparse
import hashlib
import json
from pathlib import Path

from pipelines.funnel_demo import encode, read_bytes
from pipelines.funnel_incremental import VERSION, fixed_json, plan_batch


def prepare(clicks, designs, variants, trade_uri, output_root, run_id, directory,
            max_files=32, max_bytes=128 * 1024 * 1024, write_s3=False):
    from pipelines.funnel_control import CONTROL, immutable_json, store_for
    from pipelines.spark_batch import resolve_inputs
    root = output_root.rstrip("/")
    if write_s3 and not root.startswith("s3://"):
        raise ValueError("S3 업로드에는 S3 출력 root가 필요합니다")
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=False)
    # Metadata inventory is not the work batch. A growing prefix must not hit
    # the legacy 10,000-object full-execution limit before selecting 32 files.
    _, captured = resolve_inputs({"clicks": [clicks]}, max_inventory_files=None)
    raw, _ = store_for(root).get(CONTROL)
    state = json.loads(raw) if raw else {"tip": None, "owner": None}
    if state.get("owner"):
        raise ValueError("이전 실행이 계산·조회 검증 중입니다")
    prior = fixed_json(state["tip"]) if state["tip"] else None
    batch = plan_batch(captured, (prior or {}).get("processed", []), max_files, max_bytes)
    trade_raw = read_bytes(trade_uri)
    trade = json.loads(trade_raw)
    trade_fixed_uri = root + "/silver/runtime/trade/runs/" + trade["run_id"] + "/manifest.json"
    fixed_raw = read_bytes(trade_fixed_uri)
    if json.loads(fixed_raw) != trade:
        raise ValueError("선택한 거래가 고정 완료 결과와 다릅니다")

    def store_document(name, document):
        local = folder / name
        local.write_bytes(encode(document))
        uri = str(local.resolve()).replace("\\", "/")
        if write_s3:
            uri = immutable_json(root, "pipelines/input-manifests/funnels-incremental/" + run_id + "/" + name, document)
        return {"uri": uri, "sha256": hashlib.sha256(read_bytes(uri)).hexdigest()}

    product_inputs, product_inventory = resolve_inputs({"designs": [designs], "variants": [variants]})
    catalog = store_document("catalog-source.json", {"status": "READY", "inputs": product_inputs, "inventory": product_inventory})
    # Reuse a materialized catalog if its original seed inventory is unchanged.
    if prior:
        old_catalog = fixed_json(prior["catalog"])
        if old_catalog.get("seed_inventory") == product_inventory:
            catalog = prior["catalog"]
    inventory = store_document("inventory.json", {"version": VERSION, "objects": captured})
    trade_ref = {"uri": trade_fixed_uri, "sha256": hashlib.sha256(fixed_raw).hexdigest()}
    if not batch["objects"] and prior and prior["trade"] == trade_ref and prior["catalog"] == catalog:
        return {"status": "NO_NEW_INPUT", "request": None}
    request = {"job": "funnels", "mode": "incremental", "run_id": run_id, "output_root": root,
               "inventory": inventory, "trade": trade_ref, "catalog": catalog, "previous": state["tip"],
               "max_files": max_files, "max_bytes": max_bytes}
    from pipelines.funnel_incremental import validate
    validate(request)
    target = folder / "request.json"
    target.write_bytes(encode(request))
    uri = str(target.resolve()).replace("\\", "/")
    if write_s3:
        uri = immutable_json(root, "pipelines/requests/funnels-incremental/" + run_id + ".json", request)
    return {"status": "PREPARED", "request": uri, "files": len(batch["objects"]),
            "bytes": batch["bytes"], "remaining_files": batch["remaining_files"], "uploaded": write_s3}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("clicks", "designs", "variants", "trade-manifest", "output-root", "run-id", "directory"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--max-files", type=int, default=32)
    parser.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--write-s3", action="store_true")
    args = parser.parse_args()
    print(encode(prepare(args.clicks, args.designs, args.variants, args.trade_manifest, args.output_root,
                         args.run_id, args.directory, args.max_files, args.max_bytes, args.write_s3)).decode())


if __name__ == "__main__":
    main()
