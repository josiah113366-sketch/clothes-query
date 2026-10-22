"""S3의 고정 입력 목록을 내려받아 기존 Silver·Gold A 배치를 실행한다."""

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4

from pipelines.gold_a import funnels as gold_funnels
from pipelines.gold_a import reviews as gold_reviews
from pipelines.gold_a import transactions as gold_trade
from pipelines.silver import clicks, members, products, reviews, transactions

REQUIRED = {
    "trade": {"orders", "order_items", "payments", "designs", "variants"},
    "funnels": {"orders", "order_items", "payments", "designs", "variants", "clicks"},
    "reviews": {"reviews", "designs", "variants"},
    "members": {"members"},
}


def location(uri):
    parsed = urlsplit(uri)
    parts = PurePosixPath(parsed.path).parts
    if (parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment
            or ".." in parts or "\\" in uri):
        raise ValueError("시간 제한 서명 URL 대신 s3://버킷/경로를 지정하세요")
    return parsed.netloc, parsed.path.lstrip("/")


def validate(config):
    allowed = {"job", "inputs", "output_root", "input_complete", "start_date", "end_date",
               "through_date", "model_version", "max_download_bytes"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("실행 설정의 필드를 확인하세요")
    job, inputs = config.get("job"), config.get("inputs")
    if job not in REQUIRED or not isinstance(inputs, dict):
        raise ValueError("job과 inputs가 필요합니다")
    optional = {"analysis", "mapping"} if job == "reviews" else set()
    if not REQUIRED[job] <= inputs.keys() or inputs.keys() - REQUIRED[job] - optional:
        raise ValueError("작업별 필수 입력과 선택 입력을 확인하세요")
    for name, uris in inputs.items():
        if not isinstance(uris, list) or not uris or any(not isinstance(u, str) for u in uris):
            raise ValueError("입력은 S3 경로의 비어 있지 않은 목록이어야 합니다")
        for uri in uris:
            if not location(uri)[1]:
                raise ValueError("입력은 버킷 전체가 아닌 데이터 파일·접두사를 지정하세요")
        if name in {"reviews", "members"} and (len(uris) != 1 or not uris[0].endswith("/")):
            raise ValueError("리뷰·회원은 날짜 폴더를 담은 접두사 하나를 지정하세요")
        if name in {"analysis", "mapping"} and (len(uris) != 1 or uris[0].endswith("/")):
            raise ValueError("분석·상품 매핑은 고정 파일 하나를 지정하세요")
    out_bucket, out_key = location(config["output_root"])
    if set(PurePosixPath(out_key).parts) & {"bronze", "ground_truth"}:
        raise ValueError("출력 루트는 Bronze·정답표 아래에 둘 수 없습니다")
    for uris in inputs.values():
        for uri in uris:
            bucket, key = location(uri)
            if bucket == out_bucket and any(
                key.rstrip("/") == base or key.startswith(base + "/")
                or uri.endswith("/") and base.startswith(key)
                for base in (out_key.rstrip("/") + "/" + layer if out_key else layer
                             for layer in ("silver/runtime", "gold_a/runtime"))
            ):
                raise ValueError("이 실행기의 결과를 Bronze 입력으로 다시 읽을 수 없습니다")
    if type(config.get("input_complete", False)) is not bool:
        raise ValueError("input_complete는 참/거짓이어야 합니다")
    if job in {"trade", "funnels"} and not config.get("input_complete"):
        raise ValueError("거래·퍼널은 전체 이력·참조 입력을 준비한 후 input_complete=true로 확인하세요")
    if job == "reviews":
        start, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
        if start > end:
            raise ValueError("리뷰 KST 시작일이 종료일보다 늦습니다")
        if "analysis" in inputs and not config.get("model_version", "").strip():
            raise ValueError("모델 결과에는 model_version이 필요합니다")
    elif job == "members":
        date.fromisoformat(config["through_date"])
    if job != "reviews" and any(k in config for k in ("start_date", "end_date", "model_version")):
        raise ValueError("거래는 날짜만 잘라 복원하지 않습니다. 날짜 인자는 리뷰에만 사용하세요")
    limit = config.get("max_download_bytes", 128 * 1024 * 1024)
    if type(limit) is not int or not 0 < limit <= 1024 * 1024 * 1024:
        raise ValueError("다운로드 한도는 1바이트~1GiB입니다. 노드 자원과 맞춰 지정하세요")


def selected_date(config, name, relative):
    """Bronze 날짜는 UTC. 리뷰는 KST 범위의 전날 UTC부터 읽는다."""
    if name not in {"members", "reviews"}:
        return True
    pieces = PurePosixPath(relative).parts
    if len(pieces) < 4:
        raise ValueError("리뷰·회원 입력은 year/month/day 폴더가 필요합니다")
    if any(not p.startswith(label + "=") for p, label in zip(pieces[:3], ("year", "month", "day"), strict=True)):
        raise ValueError("입력 폴더는 year/month/day 순서여야 합니다")
    day = date.fromisoformat("-".join(p.split("=", 1)[1] for p in pieces[:3]))
    if name == "members":
        return day <= date.fromisoformat(config["through_date"])
    return date.fromisoformat(config["start_date"]) - timedelta(days=1) <= day <= date.fromisoformat(config["end_date"])


def download(config, s3, root):
    plan, seen, size = [], set(), 0
    paths, references = {}, {}
    for name, uris in config["inputs"].items():
        folder = root / name / ("reviews" if name == "reviews" else "")
        paths[name] = str(folder.parent if name == "reviews" else folder)
        before = len(plan)
        for uri in uris:
            bucket, key = location(uri)
            if uri.endswith("/"):
                pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key)
                objects = (obj for page in pages for obj in page.get("Contents", []))
            else:
                objects = [{"Key": key, **s3.head_object(Bucket=bucket, Key=key)}]
            for obj in objects:
                source_key = obj["Key"]
                relative = source_key[len(key):] if uri.endswith("/") else PurePosixPath(key).name
                part = PurePosixPath(relative)
                if part.suffix not in {".json", ".jsonl", ".csv"}:
                    continue
                if part.is_absolute() or ".." in part.parts or "\\" in relative:
                    raise ValueError("입력 객체의 경로가 올바르지 않습니다")
                if not selected_date(config, name, relative):
                    continue
                if name == "members" and not members.PARTITION.search(relative):
                    raise ValueError("회원 파일은 members-events+파티션+오프셋.json 형식이어야 합니다")
                if name == "reviews" and part.suffix != ".jsonl":
                    raise ValueError("리뷰 원문은 JSONL 파일이어야 합니다")
                identity = (bucket, source_key)
                if identity in seen:
                    raise ValueError("중첩 입력 접두사 또는 중복 객체가 있습니다")
                seen.add(identity)
                size += obj.get("Size", obj.get("ContentLength", 0))
                plan.append((name, bucket, source_key, folder / part, obj["ETag"]))
        if len(plan) == before:
            raise FileNotFoundError("선택한 입력에서 지원하는 파일을 찾지 못했습니다: " + name)
    if size > config.get("max_download_bytes", 128 * 1024 * 1024):
        raise ValueError("입력 크기가 실행 다운로드 한도를 넘습니다")
    inventory = []
    used_paths = set()
    for name, bucket, key, target, etag in plan:
        if target in used_paths:
            raise ValueError("서로 다른 입력 객체의 로컬 경로가 겹칩니다")
        used_paths.add(target)
        response = s3.get_object(Bucket=bucket, Key=key, IfMatch=etag)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        body = response["Body"]
        try:
            with target.open("wb") as handle:
                for chunk in iter(lambda stream=body: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    handle.write(chunk)
        finally:
            body.close()
        uri = f"s3://{bucket}/{key}"
        references[str(target)] = uri
        inventory.append({"input": name, "uri": uri, "etag": etag,
                          "version_id": response.get("VersionId"), "sha256": digest.hexdigest()})
        if name in {"analysis", "mapping"}:
            paths[name] = str(target)
    return paths, references, inventory


def relocate(value, replacements):
    if isinstance(value, dict):
        return {key: relocate(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate(item, replacements) for item in value]
    if isinstance(value, str):
        value = value.removeprefix("\\\\?\\")
        for old, new in sorted(replacements.items(), key=lambda row: -len(row[0])):
            if value == old or value.startswith(old + os.sep):
                return new + value[len(old):].replace("\\", "/")
    return value


def put_json(s3, uri, value, **conditions):
    bucket, key = location(uri)
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(value, ensure_ascii=False).encode("utf-8"),
                  ContentType="application/json", **conditions)


def current_condition(s3, uri):
    from botocore.exceptions import ClientError

    bucket, key = location(uri)
    try:
        return {"IfMatch": s3.head_object(Bucket=bucket, Key=key)["ETag"]}
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchKey", "NotFound"}:
            raise
        return {"IfNoneMatch": "*"}


def publish(s3, local, remote, replacements):
    """고유 실행 폴더만 업로드. mutable current는 상위 실행 기록에서만 갱신한다."""
    if os.name == "nt":
        local = Path("\\\\?\\" + str(local.resolve()).removeprefix("\\\\?\\"))
    manifests = []
    for path in sorted(local.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        uri = remote + "/" + path.relative_to(local).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            body = "".join(json.dumps(relocate(json.loads(line), replacements), ensure_ascii=False) + "\n"
                           for line in text.splitlines() if line.strip())
        else:
            row = relocate(json.loads(text), replacements)
            body = json.dumps(row, ensure_ascii=False)
            if path.name == "current.json":
                manifests.append({"uri": uri, "status": row["status"], "run_id": row.get("run_id")})
        bucket, key = location(uri)
        s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"),
                      ContentType="application/json" if path.suffix == ".json" else "application/x-ndjson")
    return manifests


def execute(config, s3, workspace, code_ref):
    validate(config)
    job = config["job"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid4().hex
    workspace = Path(workspace).resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("이전 실행이 섞이지 않도록 비어 있는 작업 폴더를 지정하세요")
    silver, gold = workspace / "silver-out", workspace / "gold-out"
    output = config["output_root"].rstrip("/")
    silver_base = f"{output}/silver/runtime/{job}/runs/{run_id}"
    gold_base = f"{output}/gold_a/runtime/{job}/runs/{run_id}"
    silver_current = f"{output}/silver/runtime/{job}/current.json"
    gold_current = f"{output}/gold_a/runtime/{job}/current.json"
    silver_condition = current_condition(s3, silver_current)
    gold_condition = current_condition(s3, gold_current) if job != "members" else {}
    paths, refs, inventory = download(config, s3, workspace / "inputs")
    refs.update({str(silver / "silver"): silver_base, str(gold / "gold_a"): gold_base})
    if job != "members":
        products.run(paths["designs"], paths["variants"], str(silver))
    if job in {"trade", "funnels"}:
        transactions.run(paths["orders"], paths["order_items"], paths["payments"], str(silver), True)
        if job == "funnels":
            clicks.run(paths["clicks"], str(silver), True)
    elif job == "reviews":
        start, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
        reviews.run(paths["reviews"], str(silver), start, end)
    else:
        members.run(paths["members"], str(silver), date.fromisoformat(config["through_date"]))
    silver_manifests = publish(s3, silver / "silver", silver_base, refs)
    record = {"runtime_run_id": run_id, "job": job, "code_ref": code_ref,
              "completed_at": datetime.now(timezone.utc).isoformat(), "inputs": inventory,
              "request": config, "coverage_status": "UNVERIFIED",
              "silver_manifests": silver_manifests,
              "status": "PASS" if all(m["status"] == "PASS" for m in silver_manifests) else "INCOMPLETE"}
    # Silver 품질 오류도 R6가 읽어야 한다. Gold 실패와 무관하게 완료된 Silver 실행은 보존한다.
    channel = f"{output}/silver/runtime/{job}"
    put_json(s3, f"{channel}/completed/{run_id}.json", record)
    put_json(s3, silver_current, record, **silver_condition)
    if record["status"] != "PASS":
        raise ValueError("Silver 품질 미완료: 검사 결과는 저장했으며 Gold A는 갱신하지 않았습니다")
    if job == "trade":
        gold_trade.run(str(silver), str(gold), str(silver))
    elif job == "funnels":
        gold_funnels.run(str(silver), str(silver), str(silver), str(gold))
    elif job == "reviews":
        gold_reviews.run_aggregate(str(silver), str(gold), start, end, str(silver), paths.get("mapping"))
        if "analysis" in paths:
            gold_reviews.run_aspects(str(silver), str(gold), start, end, str(silver), paths["analysis"],
                                    config["model_version"], paths.get("mapping"))
    if job != "members":
        record = {**record, "completed_at": datetime.now(timezone.utc).isoformat(),
                  "gold_manifests": publish(s3, gold / "gold_a", gold_base, refs),
                  "review_scores": "PROVIDED" if "analysis" in paths else "NOT_REQUESTED"}
        channel = f"{output}/gold_a/runtime/{job}"
        put_json(s3, f"{channel}/completed/{run_id}.json", record)
        put_json(s3, gold_current, record, **gold_condition)
    return record


def main():
    parser = argparse.ArgumentParser(description="S3 → Silver → Gold A 수동 실행")
    parser.add_argument("--config", help="JSON 설정 파일. 생략하면 BATCH_CONFIG 환경 변수")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8") if args.config else os.environ["BATCH_CONFIG"])
    code_ref = os.environ.get("PIPELINE_CODE_REF", "")
    if not code_ref or code_ref == "unknown":
        raise ValueError("이미지 빌드 시 PIPELINE_CODE_REF를 Git 커밋으로 지정하세요")
    import boto3

    # Pod 종료 시 원문이 남지 않도록 작업 폴더를 제거한다. 원문·자격증명은 출력하지 않는다.
    with tempfile.TemporaryDirectory(prefix="batch-") as folder:
        result = execute(config, boto3.client("s3"), folder, code_ref)
    print(json.dumps({"job": result["job"], "runtime_run_id": result["runtime_run_id"], "status": result["status"]}))


if __name__ == "__main__":
    main()
