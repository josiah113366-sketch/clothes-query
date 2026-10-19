"""Gold A의 결과 입출력과 Silver 품질 검사."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from pipelines.silver.common import publish_bundle

def _uri(root: str, *parts: str) -> str:
    return "/".join((root.rstrip("/"), *(part.strip("/") for part in parts)))


def _s3_location(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 경로는 s3://버킷/접두사 형식이어야 합니다")
    return parsed.netloc, parsed.path.lstrip("/")


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
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".gold-a-", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(body)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def read_rows(uri: str) -> list[dict]:
    rows = []
    for number, line in enumerate(_read_text(uri).splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"결과 파일 {uri}:{number}: JSON 파싱 실패") from exc
        if not isinstance(row, dict):
            raise ValueError("결과 행은 JSON 객체여야 합니다")
        rows.append(row)
    return rows


def load_silver(manifest_uri: str, expected: dict, names: list[str]) -> tuple[dict, dict]:
    """대표 결과 한 묶음만 읽고 품질 미완료이면 출력 갱신 전에 중단한다."""
    manifest = json.loads(_read_text(manifest_uri))
    if not isinstance(manifest, dict) or manifest.get("status") != "PASS":
        raise ValueError("Silver 품질 상태가 PASS가 아니므로 Gold A 갱신을 중단합니다")
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Silver manifest의 처리 범위가 요청과 다릅니다")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("Silver manifest에 outputs가 없습니다")
    # 거래는 데이터셋명, 회원·리뷰는 파일명을 outputs 키로 사용한다.
    dq_path = outputs.get("dq_results") or outputs.get("dq_results.jsonl")
    if not isinstance(dq_path, str):
        raise ValueError("Silver 품질 결과 경로가 없습니다")
    checks = read_rows(dq_path)
    if not checks or any(row.get("status") != "PASS" or row.get("quarantined_count") != 0 for row in checks):
        raise ValueError("Silver 품질 결과가 불완전하므로 Gold A 갱신을 중단합니다")
    loaded = {}
    for name in names:
        path = outputs.get(name)
        if not isinstance(path, str):
            raise ValueError("Silver manifest에 필요한 결과 경로가 없습니다")
        loaded[name] = read_rows(path)
    return loaded, {"manifest_path": manifest_uri, "run_id": manifest.get("run_id"),
                    "check_version": manifest.get("check_version"), "dq_results": checks,
                    "outputs": outputs}


def save_gold(base: str, result: dict[str, list[dict]], inputs: dict) -> dict:
    return publish_bundle(base, result, {"status": "PASS", "inputs": inputs,
                          "check_version": "gold-a.connection.v1"}, _write_text)
