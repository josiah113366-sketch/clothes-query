"""Gold A의 결과 입출력과 Silver 품질 검사."""
from __future__ import annotations

import json
from datetime import date
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


def require_pass(silver: dict) -> None:
    checks = silver.get("dq_results")
    if not checks or any(row.get("status") != "PASS" or row.get("quarantined_count") != 0 for row in checks):
        raise ValueError("Silver 품질 결과가 불완전합니다")


def load_products(root: str) -> tuple[list[dict], dict]:
    loaded, ref = load_silver(_uri(root, "silver", "products", "current.json"), {},
                             ["silver_product_variant", "silver_product_design"])
    designs = {row["product_code"] for row in loaded["silver_product_design"]}
    catalog = product_index(loaded["silver_product_variant"])
    if any(code not in designs for code in catalog.values()):
        raise ValueError("상품의 디자인 기준정보 연결이 없습니다")
    return loaded["silver_product_variant"], ref


def product_index(products: list[dict]) -> dict[str, int]:
    result = {}
    for row in products:
        article, code = row.get("article_id"), row.get("product_code")
        if not isinstance(article, str) or not article.strip() or isinstance(code, bool) or not isinstance(code, int):
            raise ValueError("상품 기준정보 키·타입 오류")
        if article in result:
            raise ValueError("상품 기준정보 article_id 중복")
        result[article] = code
    return result


def connect_reviews(rows: list[dict], products: list[dict], mapping: list[dict] | None = None) -> list[dict]:
    catalog, aliases = product_index(products), {}
    for row in mapping or []:
        source, article = row.get("product_id"), row.get("article_id")
        if not isinstance(source, str) or not source.strip() or not isinstance(article, str) or article not in catalog:
            raise ValueError("리뷰 상품 매핑의 원천 키 또는 대상 상품 오류")
        if source in aliases:
            raise ValueError("리뷰 상품 매핑 product_id 중복")
        aliases[source] = article
    result = []
    for row in rows:
        source = row["product_id"]
        article = aliases.get(source, source)
        if article not in catalog:
            raise ValueError("리뷰 상품 연결 실패: 상품 기준정보 또는 명시적 매핑이 필요합니다")
        result.append({**row, "article_id": article, "product_code": catalog[article]})
    return result


def replacement(start: str | None, end: str | None, articles: list[str] | None = None,
                model_version: str | None = None) -> dict | None:
    if start is None and end is None and not articles:
        return None
    if start is None or end is None or date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("부분 재처리는 올바른 시작·종료 날짜가 필요합니다")
    return {"start_date": start, "end_date": end, "article_ids": sorted(set(articles or [])),
            "model_version": model_version}


def _row_date(row: dict) -> str:
    for field in ("sales_date_kst", "review_date_kst", "funnel_date_kst", "first_view_at_kst", "hour_start_kst"):
        if field in row:
            value = str(row[field])[:10]
            date.fromisoformat(value)
            return value
    raise ValueError("부분 재처리 대상 행에 날짜 기준이 없습니다")


def _selected(row: dict, scope: dict) -> bool:
    if not scope["start_date"] <= _row_date(row) <= scope["end_date"]:
        return False
    if scope.get("model_version") and "model_version" in row and row["model_version"] != scope["model_version"]:
        return False
    # 시간별 전체 주문 지표는 상품별 행이 아니므로 해당 날짜를 전체 재계산한다.
    if scope["article_ids"] and "hour_start_kst" not in row:
        if "article_id" not in row:
            raise ValueError("상품 부분 재처리는 article_id 연결 후 사용할 수 있습니다")
        return row["article_id"] in scope["article_ids"]
    return True


def _grain(row: dict) -> tuple:
    if "hour_start_kst" in row:
        return (row["hour_start_kst"],)
    if "first_view_at_kst" in row:
        return (row["session_id"], row["article_id"])
    key = (_row_date(row), row.get("article_id", row.get("product_id")))
    return key + ((row["aspect"], row["model_version"]) if "aspect" in row else ())


def save_gold(base: str, result: dict[str, list[dict]], inputs: dict, reprocess: dict | None = None) -> dict:
    previous_ref = None
    if reprocess:
        try:
            previous = json.loads(_read_text(_uri(base, "current.json")))
        except FileNotFoundError as exc:
            raise ValueError("부분 재처리 전에 전체 결과를 먼저 만들어야 합니다") from exc
        if previous.get("status") != "PASS":
            raise ValueError("기존 Gold A 결과가 정상 완료 상태가 아닙니다")
        old = {name: read_rows(path) for name, path in previous["outputs"].items()}
        combined = {}
        for name in sorted(set(old) | set(result)):
            kept = [row for row in old.get(name, []) if not _selected(row, reprocess)]
            updated = [row for row in result.get(name, []) if _selected(row, reprocess)]
            combined[name] = sorted(kept + updated, key=_grain)
        result = combined
        previous_ref = {"manifest_path": _uri(base, "current.json"), "run_id": previous.get("run_id"),
                        "outputs": previous["outputs"], "inputs": previous.get("inputs"),
                        "reprocess": previous.get("reprocess"), "previous_result": previous.get("previous_result")}
    for rows in result.values():
        keys = [_grain(row) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("Gold A 고유 키 중복")
    return publish_bundle(base, result, {"status": "PASS", "inputs": inputs,
                          "reprocess": reprocess, "previous_result": previous_ref,
                          "check_version": "gold-a.metrics.v2"}, _write_text)
