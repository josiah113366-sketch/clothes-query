"""Gold A의 결과 입출력과 Silver 품질 검사."""
from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import wraps
from inspect import signature
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pipelines.silver.common import publish_bundle


def exclusive_output(dataset: str):
    """로컬 거래/퍼널의 현재 결과 읽기부터 공개까지 단일 실행으로 보호한다."""
    def decorate(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            root = str(signature(function).bind(*args, **kwargs).arguments["output_root"])
            if root.startswith("s3://"):
                return function(*args, **kwargs)
            lock = Path(root) / "gold_a" / dataset / ".writer.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                raise ValueError("같은 Gold 출력에 실행 중이거나 미정리된 잠금이 있습니다") from exc
            try:
                os.write(descriptor, str(os.getpid()).encode("ascii"))
                return function(*args, **kwargs)
            finally:
                os.close(descriptor)
                lock.unlink()
        return guarded
    return decorate

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
            raise ValueError("결과 행은 JSON 객체여야 합니다")  # noqa: TRY004 - 외부 결과 검증 오류 계약 유지
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
        raise ValueError("Silver manifest에 outputs가 없습니다")  # noqa: TRY004 - manifest 검증 오류 계약 유지
    # 거래는 데이터셋명, 회원·리뷰는 파일명을 outputs 키로 사용한다.
    dq_path = outputs.get("dq_results") or outputs.get("dq_results.jsonl")
    if not isinstance(dq_path, str):
        raise ValueError("Silver 품질 결과 경로가 없습니다")  # noqa: TRY004 - manifest 검증 오류 계약 유지
    checks = read_rows(dq_path)
    if not checks or any(row.get("status") != "PASS" or row.get("quarantined_count") != 0 for row in checks):
        raise ValueError("Silver 품질 결과가 불완전하므로 Gold A 갱신을 중단합니다")
    loaded = {}
    for name in names:
        path = outputs.get(name)
        if not isinstance(path, str):
            raise ValueError("Silver manifest에 필요한 결과 경로가 없습니다")  # noqa: TRY004 - manifest 검증 오류 계약 유지
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
                          "published_at": datetime.now(timezone.utc).isoformat(),
                          "check_version": "gold-a.metrics.v2"}, _write_text)


def load_scoped_trade(root: str) -> tuple[dict, dict]:
    """부분 공개는 전체 입력을 준비했다는 명시적 확인이 있는 거래 묶음만 허용한다."""
    uri = _uri(root, "silver", "transactions", "current.json")
    manifest = json.loads(_read_text(uri))
    if manifest.get("input_completeness") != "DECLARED_COMPLETE":
        raise ValueError("범위별 갱신에는 Silver --input-complete 확인이 필요합니다")
    if manifest.get("status") not in {"PASS", "INCOMPLETE"}:
        raise ValueError("지원하지 않는 Silver 품질 상태")
    names = ("orders_current", "silver_order_items", "payment_attempts", "dq_results",
             "quarantined_records", "impact_candidates")
    outputs = manifest["outputs"]
    trade = {name: read_rows(outputs[name]) for name in names}
    checks = trade["dq_results"]
    if {row.get("source_dataset") for row in checks} != {"orders", "order_items", "payments"}:
        raise ValueError("거래 품질 결과가 부족합니다")
    if any(row.get("status") not in {"PASS", "INCOMPLETE"} for row in checks):
        raise ValueError("거래 품질 상태를 판정할 수 없습니다")
    if sum(row.get("quarantined_count", -1) for row in checks) != len(trade["quarantined_records"]):
        raise ValueError("품질 건수와 오류 기록이 일치하지 않습니다")
    if (manifest["status"] == "PASS") != (not trade["quarantined_records"]):
        raise ValueError("Silver 상태와 오류 기록이 일치하지 않습니다")
    return trade, {"manifest_path": uri, "run_id": manifest.get("run_id"),
                   "outputs": outputs, "dq_results": checks,
                   "input_completeness": manifest["input_completeness"]}


def previous_gold(base: str) -> dict | None:
    uri = _uri(base, "current.json")
    # 범위별 거래/퍼널은 현재 로컬 실행만 지원한다. 읽기 실패를 없음으로 숨기지 않는다.
    if not Path(uri).exists():
        return None
    previous = json.loads(_read_text(uri))
    if previous.get("status") not in {"PASS", "PARTIAL"}:
        raise ValueError("기존 Gold 결과 상태를 읽을 수 없습니다")
    return previous


def plan_trade_holds(trade: dict, previous: dict | None, tables: list[str],
                     clicks: list[dict] | None = None) -> tuple[list[dict], set[str], list[dict]]:
    """모든 현재/이전 후보로 범위를 찾는다. 추적 불가는 관련 결과 묶음 전체 보류."""
    issues = trade["quarantined_records"]
    if not issues:
        return [], set(), []
    candidates = list(trade["impact_candidates"])
    unresolved = False
    if previous:
        ref = previous.get("inputs", {}).get("silver_transactions", {})
        path = ref.get("outputs", {}).get("impact_candidates")
        if path:
            candidates += read_rows(path)
        else:
            # 예전 결과의 연결 정보가 없으면 좁혀 갱신하지 않는다.
            unresolved = True
        candidates += previous.get("held_context", [])
    affected = {row["order_id"] for row in issues if row.get("order_id")}
    key_fields = {"orders": "order_id", "order_items": "order_item_id", "payments": "payment_id"}
    for issue in issues:
        if not issue.get("order_id") or not issue.get("record_key"):
            unresolved = True
        field = key_fields.get(issue.get("source_dataset"))
        matches = [row for row in candidates if row.get("source_dataset") == issue.get("source_dataset")
                   and field and row.get(field) == issue.get("record_key")]
        if not matches:
            unresolved = True
        for row in matches:
            if row.get("order_id"):
                affected.add(row["order_id"])
            else:
                unresolved = True
    context = [row for row in candidates if row.get("order_id") in affected]
    orders, items, payments = defaultdict(list), defaultdict(set), defaultdict(list)
    for row in context:
        key = row["order_id"]
        if not row.get("valid"):
            unresolved = True
        if row["source_dataset"] == "orders":
            orders[key].append(row)
        elif row["source_dataset"] == "order_items" and row.get("article_id"):
            items[key].add(row["article_id"])
        elif row["source_dataset"] == "payments":
            payments[key].append(row)
    holds = {}

    def hold(table, key):
        holds[(table, json.dumps(key, sort_keys=True))] = {
            "table": table, "key": key, "reason": "UPSTREAM_TRANSACTION_ERROR",
            "order_ids": sorted(affected),
            "error_refs": [{key: issue.get(key) for key in (
                "source_dataset", "record_key", "error_code", "source_file", "source_line")}
                for issue in issues]}

    def kst(value):
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        if parsed.tzinfo is None:
            raise ValueError("시간대가 없는 후보 시각")
        return parsed.astimezone(ZoneInfo("Asia/Seoul"))

    try:
        for order_id in affected:
            if not orders[order_id] or not items[order_id]:
                unresolved = True
                continue
            if "order_sales_hourly" in tables:
                for order in orders[order_id]:
                    # 주문 오류도 포함하므로 생성 시각의 주문 수를 함께 보류한다.
                    hold("order_sales_hourly", {"hour_start_kst": kst(order["ordered_at"]).replace(
                        minute=0, second=0, microsecond=0).isoformat()})
            for payment in payments[order_id]:
                at = kst(payment["completed_at"])
                if "order_sales_hourly" in tables:
                    hold("order_sales_hourly", {"hour_start_kst": at.replace(
                        minute=0, second=0, microsecond=0).isoformat()})
                if "product_sales_daily" in tables:
                    for article in items[order_id]:
                        hold("product_sales_daily", {"sales_date_kst": str(at.date()), "article_id": article})
            if "funnel_daily" in tables:
                for order in orders[order_id]:
                    session = order["session_id"]
                    for article in items[order_id]:
                        hold("funnel_session_product", {"session_id": session, "article_id": article})
                        views = [kst(row["event_time_kst"]) for row in clicks or []
                                 if row["session_id"] == session and row["article_id"] == article
                                 and row["event_type"] == "view"]
                        if views:
                            hold("funnel_daily", {"funnel_date_kst": str(min(views).date()), "article_id": article})
                if previous:
                    path = previous["outputs"].get("funnel_session_product.jsonl")
                    for row in read_rows(path) if path else []:
                        if any(row["session_id"] == order.get("session_id") for order in orders[order_id]):
                            hold("funnel_session_product", {"session_id": row["session_id"], "article_id": row["article_id"]})
                            hold("funnel_daily", {"funnel_date_kst": row["first_view_at_kst"][:10], "article_id": row["article_id"]})
    except (KeyError, ValueError, TypeError):
        unresolved = True
    # 주문/항목 자체 오류에서 과거 결제 참조가 없으면 과거 매출 영향도 확정할 수 없다.
    if any(row.get("source_dataset") != "payments" for row in issues):
        unresolved = True
    if unresolved:
        holds = {}
        for table in tables:
            hold(table, {})
    return list(holds.values()), affected, list({json.dumps(row, sort_keys=True): row for row in context}.values())


def healthy_trade(trade: dict, affected: set[str]) -> dict:
    """계산용 정상 행만 분리한다. 원본 DQ를 PASS로 덮어쓰지 않는다."""
    return {**trade,
            "orders_current": [row for row in trade["orders_current"] if row["order_id"] not in affected],
            "silver_order_items": [row for row in trade["silver_order_items"] if row["order_id"] not in affected],
            "payment_attempts": [row for row in trade["payment_attempts"] if row["order_id"] not in affected]}


def save_scoped_gold(base: str, result: dict, inputs: dict, holds: list[dict],
                     context: list[dict], previous: dict | None) -> dict:
    """정상 범위 교체와 보류 상태를 단일 manifest로 함께 공개한다."""
    def matches(row, key):
        return all(row.get(field) == value for field, value in key.items())

    old = {} if previous is None else {name: read_rows(path) for name, path in previous["outputs"].items()}
    for name, rows in result.items():
        table = name.removesuffix(".jsonl")
        scopes = [row for row in holds if row["table"] == table]
        frozen = [row for row in old.get(name, []) if any(matches(row, scope["key"]) for scope in scopes)]
        fresh = [row for row in rows if not any(matches(row, scope["key"]) for scope in scopes)]
        result[name] = sorted(frozen + fresh, key=_grain)
        keys = [_grain(row) for row in result[name]]
        if len(keys) != len(set(keys)):
            raise ValueError("범위별 공개 결과의 고유 키가 중복됩니다")
        for scope in scopes:
            before = next((row for row in (previous or {}).get("held_scopes", [])
                           if row["table"] == table and matches(scope["key"], row["key"])), None)
            present = any(matches(row, scope["key"]) for row in old.get(name, []))
            scope["previous_result_available"] = present
            scope["last_normal_result"] = (before.get("last_normal_result") if before else
                {"run_id": previous.get("run_id"), "published_at": previous.get("published_at"),
                 "outputs": previous["outputs"]} if previous and present else None)
    try:
        return publish_bundle(base, result, {"status": "PARTIAL" if holds else "PASS", "inputs": inputs,
            "held_scopes": holds, "held_context": context if holds else [],
            "published_at": datetime.now(timezone.utc).isoformat(), "check_version": "gold-a.scoped.v1"}, _write_text)
    except Exception as exc:
        # 숫자 공개 실패는 이전 포인터를 유지한다. 오류 메시지/원문 대신 유형만 기록한다.
        from uuid import uuid4
        try:
            _write_text(_uri(base, "failed-runs", "failed-" + uuid4().hex + ".json"), json.dumps({
                "status": "FAILED", "failed_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__, "previous_run_id": (previous or {}).get("run_id")}, indent=2))
        except OSError:
            pass  # 저장소 자체 장애라면 실패 기록도 불가능할 수 있다. 원래 실패는 다시 전달한다.
        raise
