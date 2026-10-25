"""고정된 원본 목록 전체에서 선택 세션을 찾고 로컬 시연 입력을 만든다. S3 쓰기 없음."""
import argparse
import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipelines.funnel_demo import VERSION, encode, read_bytes


def scan_click_object(item, sessions, s3):
    parsed = urlsplit(item["uri"])
    response = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"), IfMatch=item["etag"])
    try:
        body = response["Body"].read()
    finally:
        response["Body"].close()
    if len(body) != item["size"] or len(body) > 64 * 1024 * 1024:
        raise ValueError("고정 클릭 객체 크기가 다릅니다")
    selected, unassigned, rows = [], 0, 0
    for number, line in enumerate(body.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        rows += 1
        try:
            raw = json.loads(line)
        except ValueError:
            unassigned += 1
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("session_id"), str):
            unassigned += 1
            continue
        if raw["session_id"] in sessions:
            selected.append((number, raw))
    return item, selected, rows, unassigned, hashlib.sha256(body).hexdigest()


def prepare(source_uri, digest, sessions, folder, run_id, s3):
    from pipelines.gold_a.funnels import build_funnels
    from pipelines.silver.clicks import build_clicks

    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sessions = sorted(set(sessions))
    if not sessions or len(sessions) > 500 or any(not isinstance(s, str) or not s.strip() for s in sessions):
        raise ValueError("고정 세션은 1~500개 문자열이어야 합니다")
    source = read_bytes(source_uri, s3)
    if hashlib.sha256(source).hexdigest() != digest:
        raise ValueError("기준 거래 manifest 해시가 다릅니다")
    original = json.loads(source)
    source_base = source_uri.rsplit("/", 1)[0]
    done_uri = source_base.rsplit("/runs/", 1)[0] + "/completed/" + original["run_id"] + ".json"
    if hashlib.sha256(read_bytes(done_uri, s3)).hexdigest() != digest or original["status"] not in {"PASS", "INCOMPLETE"}:
        raise ValueError("완료된 거래 실행이 필요합니다")
    fixed = [item for item in original["input_objects"] if item["dataset"] == "clicks"]
    if not fixed or len({item["uri"] for item in fixed}) != len(fixed):
        raise ValueError("고정 클릭 원본 목록이 없거나 중복입니다")
    events, scan_records, unassigned, source_rows = [], [], 0, 0
    scan_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        def scan(item):
            return scan_click_object(item, set(sessions), s3)
        for item, selected, rows, bad, sha in pool.map(scan, fixed):
            events.extend(raw for _, raw in selected)
            source_rows += rows
            unassigned += bad
            scan_records.append({**item, "sha256": sha, "selected_rows": len(selected)})
    scan_seconds = time.monotonic() - scan_started
    found = {row["session_id"] for row in events}
    if found != set(sessions):
        raise ValueError("일부 선택 세션의 클릭 이력이 없습니다")
    # 전체 파일 내용은 보관하지 않고 선택 행만 저장한다. 고정 목록 밖 미래 이력은 포함하지 않는다.
    frames, silver_files = {}, []
    for table in ("orders_current", "silver_order_items", "payment_attempts", "order_amount_checks", "dq_order_results"):
        uri = original["outputs"][table]
        if uri != source_base + "/" + table:
            raise ValueError("거래 출력이 기준 실행 밖입니다")
        parsed = urlsplit(uri)
        objects = sorted([item for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=parsed.netloc, Prefix=parsed.path.lstrip("/") + "/") for item in page.get("Contents", [])
            if item["Key"].endswith(".parquet")], key=lambda item: item["Key"])
        chunks = []
        for item in objects:
            response = s3.get_object(Bucket=parsed.netloc, Key=item["Key"], IfMatch=item["ETag"])
            try:
                body = response["Body"].read()
            finally:
                response["Body"].close()
            chunks.append(pq.ParquetFile(io.BytesIO(body)).read())
            silver_files.append({"uri": "s3://" + parsed.netloc + "/" + item["Key"], "etag": item["ETag"],
                                 "size": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        if not chunks:
            raise ValueError("거래 Parquet이 없습니다")
        frame = pa.concat_tables(chunks)
        if frame.num_rows != original["output_counts"][table]:
            raise ValueError("거래 테이블 행 수가 다릅니다")
        if table == "orders_current":
            frame = frame.filter(pc.is_in(frame["session_id"], value_set=pa.array(sessions)))
            order_ids = frame["order_id"].to_pylist()
        else:
            frame = frame.filter(pc.is_in(frame["order_id"], value_set=pa.array(order_ids, type=pa.string())))
        frames[table] = frame.to_pylist()
    checks = frames["order_amount_checks"]
    if ({row["order_id"] for row in checks} != set(order_ids) or any(row["status"] != "PASS" for row in checks)
            or any(row["active_error_count"] for row in frames["dq_order_results"])):
        raise ValueError("선택 주문에 미완료 검사·활성 오류가 있습니다")
    clean = build_clicks(events)
    if clean["quarantined_records"]:
        raise ValueError("선택 클릭에 형식·내용 오류가 있습니다")
    articles = {row["article_id"] for row in clean["click_events"]} | {row["article_id"] for row in frames["silver_order_items"]}
    products = {}
    for name in ("variants", "designs"):
        item = next(item for item in original["input_objects"] if item["dataset"] == name)
        parsed = urlsplit(item["uri"])
        response = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"), IfMatch=item["etag"])
        try:
            body = response["Body"].read()
        finally:
            response["Body"].close()
        table = pq.ParquetFile(io.BytesIO(body)).read()
        key, values = ("article_id", articles) if name == "variants" else ("product_code", products["variants"]["product_code"].unique().to_pylist())
        table = table.filter(pc.is_in(table[key], value_set=pa.array(sorted(values), type=table[key].type)))
        products[name] = table
    if set(products["variants"]["article_id"].to_pylist()) != articles:
        raise ValueError("선택 상품 기준정보가 없습니다")
    reference_trade = {**frames, "dq_results": [{"status": "PASS", "quarantined_count": 0}]}
    expected = build_funnels(clean, reference_trade, products["variants"].to_pylist())
    if any(len(rows) > 50000 for rows in expected.values()):
        raise ValueError("시연 검수 한도를 초과했습니다")
    objects = {}
    counts = {}
    data = {"clicks": events, "orders": frames["orders_current"], "items": frames["silver_order_items"],
            "payments": frames["payment_attempts"], "checks": checks, "order_quality": frames["dq_order_results"]}
    for name, rows in data.items():
        path = folder / (name + ".jsonl")
        path.write_bytes(b"".join(encode(row) + b"\n" for row in rows))
        counts[name] = len(rows)
    for name, table in products.items():
        pq.write_table(table, folder / (name + ".parquet"))
    (folder / "expected.json").write_bytes(encode(expected))
    for name in [*data, "designs", "variants", "expected"]:
        extension = ".jsonl" if name in data else ".json" if name == "expected" else ".parquet"
        path = folder / (name + extension)
        objects[name] = {"file": path.name, "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"version": VERSION, "coverage_status": "FIXED_SOURCE_INVENTORY_COMPLETE", "session_ids": sessions,
                "source_trade": {"manifest": source_uri, "sha256": digest, "run_id": original["run_id"], "quality_status": original["status"]},
                "selected_order_quality": "PASS", "objects": objects, "counts": counts,
                "preparation_metrics": {"source_files_scanned": len(fixed), "source_bytes_scanned": sum(item["size"] for item in fixed),
                    "source_rows_scanned": source_rows, "unassigned_source_rows": unassigned,
                    "scan_seconds": round(scan_seconds, 6), "total_seconds": round(time.monotonic() - started, 6)},
                "scope_note": "고정 원본 목록의 식별 가능한 선택 세션 이력. 목록 밖 미래 이벤트·전체 전환율을 뜻하지 않음.",
                "scan_objects": scan_records, "silver_objects": silver_files}
    raw = encode(manifest)
    (folder / "selection-manifest.json").write_bytes(raw)
    request = {"job": "funnels", "mode": "demo", "run_id": run_id, "output_root": (folder / "runtime").as_posix(),
               "selection_manifest": (folder / "selection-manifest.json").as_posix(), "selection_sha256": hashlib.sha256(raw).hexdigest()}
    (folder / "request.json").write_bytes(encode(request))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-manifest", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--sessions", required=True, help="JSON 배열이 든 로컬 파일")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    import boto3
    result = prepare(args.trade_manifest, args.sha256, json.loads(Path(args.sessions).read_text(encoding="utf-8")),
                     args.output, args.run_id, boto3.client("s3", region_name="ap-northeast-1"))
    print(encode({"status": "LOCAL_ONLY", "counts": result["counts"], "preparation_metrics": result["preparation_metrics"]}).decode())


if __name__ == "__main__":
    main()
