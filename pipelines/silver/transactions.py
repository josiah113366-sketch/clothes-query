"""거래 업무 행을 정상 결과·격리 기록·품질 요약으로 나눈다.

로컬 JSONL 입출력까지 제공한다. CDC 해석·S3 연결·공통 YAML 실행 연결은 별도다.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
CHECK_VERSION = "transactions.v1"  # 공통 YAML 버전과 구분한다.
ORDER_STATUSES = {
    "PLACED", "PAID", "SHIPPED", "DELIVERED",
    "PAYMENT_FAILED", "CANCELLED", "REFUNDED",
}


class _RowError(ValueError):
    def __init__(self, field: str, code: str, message: str):
        super().__init__(message)
        self.field, self.code = field, code


def _required_text(row: dict, field: str) -> str:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _RowError(field, "MISSING_FIELD", "필수 정보가 없습니다")
    if not isinstance(value, str):
        raise _RowError(field, "TYPE_MISMATCH", "문자열이어야 합니다")
    return value


def _time(row: dict, field: str) -> datetime:
    value = _required_text(row, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _RowError(field, "TYPE_MISMATCH", "ISO 시각이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _RowError(field, "INVALID_VALUE", "시간대가 없습니다")
    return parsed.astimezone(UTC)


def _integer(row: dict, field: str, minimum: int) -> int:
    value = row.get(field)
    if value is None:
        raise _RowError(field, "MISSING_FIELD", "필수 정보가 없습니다")
    if isinstance(value, bool) or not isinstance(value, int):
        raise _RowError(field, "TYPE_MISMATCH", "정수여야 합니다")
    if value < minimum:
        raise _RowError(field, "INVALID_VALUE", "허용 최솟값보다 작습니다")
    return value


def _order(raw: dict) -> dict:
    status = _required_text(raw, "status")
    if status not in ORDER_STATUSES:
        raise _RowError("status", "INVALID_VALUE", "지원하지 않는 주문 상태입니다")
    ordered, updated = _time(raw, "ordered_at"), _time(raw, "updated_at")
    if updated < ordered:
        raise _RowError("updated_at", "INVALID_VALUE", "주문 생성보다 변경 시각이 빠릅니다")
    return {
        "order_id": _required_text(raw, "order_id"),
        "member_id": _required_text(raw, "member_id"),
        "session_id": _required_text(raw, "session_id"),
        "status": status, "status_reason": raw.get("status_reason"),
        "total_amount": _integer(raw, "total_amount", 1),
        "ordered_at_utc": ordered.isoformat(),
        "ordered_at_kst": ordered.astimezone(KST).isoformat(),
        "updated_at_utc": updated.isoformat(),
        "updated_at_kst": updated.astimezone(KST).isoformat(),
    }


def _item(raw: dict) -> dict:
    quantity, unit_price = _integer(raw, "quantity", 1), _integer(raw, "unit_price", 1)
    return {
        "order_item_id": _required_text(raw, "order_item_id"),
        "order_id": _required_text(raw, "order_id"),
        "article_id": _required_text(raw, "article_id"),
        "quantity": quantity, "unit_price": unit_price,
        "item_amount": quantity * unit_price,
    }


def _payment(raw: dict) -> dict:
    status = _required_text(raw, "status")
    if status not in {"SUCCESS", "FAILED"}:
        raise _RowError("status", "INVALID_VALUE", "지원하지 않는 결제 결과입니다")
    code = raw.get("failure_code")
    if status == "FAILED":
        _required_text(raw, "failure_code")
    elif code is not None:
        raise _RowError("failure_code", "INVALID_VALUE", "성공 결제의 실패 코드는 NULL이어야 합니다")
    requested, completed = _time(raw, "requested_at"), _time(raw, "completed_at")
    if completed < requested:
        raise _RowError("completed_at", "INVALID_VALUE", "결과 시각이 요청 시각보다 빠릅니다")
    return {
        "payment_id": _required_text(raw, "payment_id"),
        "order_id": _required_text(raw, "order_id"),
        "attempt_no": _integer(raw, "attempt_no", 1),
        "method": _required_text(raw, "method"), "pg": _required_text(raw, "pg"),
        "amount": _integer(raw, "amount", 1), "status": status, "failure_code": code,
        "requested_at_utc": requested.isoformat(),
        "requested_at_kst": requested.astimezone(KST).isoformat(),
        "completed_at_utc": completed.isoformat(),
        "completed_at_kst": completed.astimezone(KST).isoformat(),
    }


def build_silver(
    orders: list[dict], order_items: list[dict], payments: list[dict]
) -> dict[str, list[dict]]:
    """정상 상세 4개와 격리·품질 결과 반환. 입출력 실패는 호출자가 처리한다."""
    inputs = {"orders": orders, "order_items": order_items, "payments": payments}
    keys = {"orders": "order_id", "order_items": "order_item_id", "payments": "payment_id"}
    normalizers = {"orders": _order, "order_items": _item, "payments": _payment}
    normalized: dict[str, dict[int, dict]] = {name: {} for name in inputs}
    errors: dict[str, dict[int, dict]] = {name: {} for name in inputs}

    def identifier(raw: object, field: str) -> str | None:
        value = raw.get(field) if isinstance(raw, dict) else None
        return value if isinstance(value, str) and value.strip() else None

    def reject(name: str, index: int, field: str, code: str, message: str,
               category: str = "INVALID") -> None:
        # 원문/회원 속성은 복사하지 않는다. 행 번호는 이번 입력 목록 내 1부터 시작한다.
        raw = inputs[name][index]
        issue = {
            "source_dataset": name, "source_row_number": index + 1,
            "record_key": identifier(raw, keys[name]),
            "order_id": identifier(raw, "order_id"),
            "field": field, "error_code": code, "reason": message,
            "category": category, "check_version": CHECK_VERSION,
        }
        if isinstance(raw, dict) and isinstance(raw.get("_input_source"), dict):
            source = raw["_input_source"]
            if isinstance(source.get("file"), str) and isinstance(source.get("line"), int):
                issue["source_file"] = source["file"]
                issue["source_line"] = source["line"]
        errors[name].setdefault(index, issue)

    # 행 오류만 분리한다. 프로그램 오류까지 잡아서 정상 완료로 숨기지 않는다.
    for name, rows in inputs.items():
        for index, raw in enumerate(rows):
            if not isinstance(raw, dict):
                reject(name, index, "record", "TYPE_MISMATCH", "객체 형태의 행이어야 합니다")
                continue
            if raw.get("_input_error"):
                reject(name, index, "record", raw["_input_error"], "업무 행 JSON 객체를 읽을 수 없습니다")
                continue
            try:
                normalized[name][index] = normalizers[name](raw)
            except _RowError as exc:
                reject(name, index, exc.field, exc.code, str(exc))

    groups: dict[str, dict[str, list[int]]] = {}
    for name, rows in inputs.items():
        groups[name] = defaultdict(list)
        for index, raw in enumerate(rows):
            key = identifier(raw, keys[name])
            if key is not None:
                groups[name][key].append(index)
        # 같은 키의 오류 행을 무시하고 다른 행을 정답으로 채택하지 않는다.
        for indices in groups[name].values():
            if any(index in errors[name] for index in indices):
                for index in indices:
                    reject(name, index, keys[name], "UNTRUSTED_GROUP",
                           "같은 키의 오류 기록이 있어 결과 확정을 보류합니다", "DEPENDENCY_BLOCKED")

    def eligible(name: str) -> list[tuple[int, dict]]:
        return [(index, row) for index, row in normalized[name].items() if index not in errors[name]]

    def reject_group(name: str, key: str, field: str, code: str, message: str,
                     category: str = "CONFLICT") -> None:
        for index in groups[name][key]:
            reject(name, index, field, code, message, category)

    # 주문의 정상 변경은 유지하고, 같은 변경 시각의 상충은 해당 주문 전체를 보류한다.
    seen_orders: dict[tuple[str, str], dict] = {}
    for _, row in eligible("orders"):
        marker = (row["order_id"], row["updated_at_utc"])
        previous = seen_orders.setdefault(marker, row)
        if previous != row:
            reject_group("orders", row["order_id"], "updated_at", "CONTENT_CONFLICT",
                         "동일 변경 시각에 주문 내용이 다릅니다")
    for name in ("order_items", "payments"):
        seen: dict[str, dict] = {}
        for _, row in eligible(name):
            key = row[keys[name]]
            previous = seen.setdefault(key, row)
            if previous != row:
                reject_group(name, key, keys[name], "CONTENT_CONFLICT", "동일 키의 업무 내용이 다릅니다")

    def unique(name: str) -> list[dict]:
        chosen = {}
        for _, row in eligible(name):
            key = ((row["order_id"], row["updated_at_utc"])
                   if name == "orders" else row[keys[name]])
            chosen.setdefault(key, row)
        return [chosen[key] for key in sorted(chosen)]

    by_order: dict[str, list[dict]] = defaultdict(list)
    for row in unique("orders"):
        by_order[row["order_id"]].append(row)
    current, history = [], []
    for order_id in sorted(by_order):
        events = sorted(by_order[order_id], key=lambda row: datetime.fromisoformat(row["updated_at_utc"]))
        previous = None
        for row in events:
            if previous is None or row["status"] != previous["status"]:
                history.append({
                    "order_id": order_id,
                    "previous_status": None if previous is None else previous["status"],
                    "status": row["status"], "status_reason": row["status_reason"],
                    "changed_at_utc": row["updated_at_utc"],
                    "changed_at_kst": row["updated_at_kst"],
                })
            previous = row
        current.append(events[-1])
    current_by_id = {row["order_id"]: row for row in current}

    # 주문 미도착은 잘못된 결제로 단정하지 않고 연결 대기로 분리한다.
    for name in ("order_items", "payments"):
        for index, row in eligible(name):
            order_id = row["order_id"]
            if order_id not in current_by_id:
                blocked = order_id in groups["orders"]
                reject(name, index, "order_id", "DEPENDENCY_BLOCKED" if blocked else "PENDING_REFERENCE",
                       "주문 오류로 연결 보류" if blocked else "연결 주문이 현재 입력에 없습니다",
                       "DEPENDENCY_BLOCKED" if blocked else "PENDING_REFERENCE")

    attempts_by_number: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in unique("payments"):
        attempts_by_number[(row["order_id"], row["attempt_no"])].append(row)
    for rows in attempts_by_number.values():
        if len(rows) > 1:
            for row in rows:
                reject_group("payments", row["payment_id"], "attempt_no", "ATTEMPT_CONFLICT",
                             "같은 주문의 동일 시도 번호에 서로 다른 결제가 있습니다")
    success_by_order: dict[str, list[dict]] = defaultdict(list)
    for row in unique("payments"):
        if row["status"] == "SUCCESS":
            success_by_order[row["order_id"]].append(row)
    for order_id, rows in success_by_order.items():
        for row in rows:
            if len(rows) > 1:
                reject_group("payments", row["payment_id"], "status", "MULTIPLE_SUCCESSES",
                             "한 주문에 성공 결제가 여러 건 있습니다")
            elif row["amount"] != current_by_id[order_id]["total_amount"]:
                reject_group("payments", row["payment_id"], "amount", "AMOUNT_MISMATCH",
                             "성공 결제 금액과 주문 금액이 다릅니다", "INVALID")

    output = {
        "orders_current": current, "order_status_history": history,
        "silver_order_items": unique("order_items"), "payment_attempts": unique("payments"),
    }
    destinations = {
        "orders": ("orders_current", "order_status_history"),
        "order_items": ("silver_order_items",), "payments": ("payment_attempts",),
    }
    quarantine, quality = [], []
    for name, rows in inputs.items():
        issues = [errors[name][index] for index in sorted(errors[name])]
        quarantine.extend(issues)
        accepted = len(unique(name))
        quality.append({
            "source_dataset": name, "check_name": "transaction_processing",
            "check_version": CHECK_VERSION, "status": "INCOMPLETE" if issues else "PASS",
            "input_count": len(rows), "accepted_count": accepted,
            "quarantined_count": len(issues),
            "duplicate_count": len(rows) - len(issues) - accepted,
            "conflict_count": sum(issue["category"] == "CONFLICT" for issue in issues),
            "pending_count": sum(issue["category"] == "PENDING_REFERENCE" for issue in issues),
            "affected_order_ids": sorted({issue["order_id"] for issue in issues if issue["order_id"]}),
            "source_row_numbers": [issue["source_row_number"] for issue in issues],
            "output_counts": {key: len(output[key]) for key in destinations[name]},
        })
    output["quarantined_records"], output["dq_results"] = quarantine, quality
    return output


def _load_jsonl(location: str) -> tuple[list[dict], list[str]]:
    """지정한 파일/폴더를 읽고 원본 파일 위치와 줄 번호를 보존한다."""
    root = Path(location).resolve()
    files = sorted(path for path in root.rglob("*")
                   if path.is_file() and path.suffix in {".json", ".jsonl"}) if root.is_dir() else [root]
    if not files:
        raise FileNotFoundError("입력 폴더에 JSONL 파일이 없습니다")
    rows = []
    for path in files:
        # 파일/인코딩 읽기 실패는 실행 실패로 전달한다. 0건 입력으로 바꾸지 않는다.
        with path.open(encoding="utf-8-sig") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                error = None
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    raw, error = {}, "PARSE_ERROR"
                if not isinstance(raw, dict):
                    raw, error = {}, "TYPE_MISMATCH"
                # 실제 CDC 해석이 연결된 것처럼 임의로 op/after를 처리하지 않는다.
                if any(field in raw for field in ("after", "before", "payload", "__op", "op")):
                    raise ValueError("CDC 입력은 업무 행으로 변환한 뒤 전달해야 합니다")
                rows.append({**raw, "_input_source": {"file": str(path), "line": number},
                             "_input_error": error})
    return rows, [str(path) for path in files]


def run(orders_input: str, order_items_input: str, payments_input: str,
        output_root: str) -> dict:
    """입력 전체를 계산하고, 결과 묶음 저장 완료 후 current.json만 원자적으로 교체한다."""
    locations = {"orders": orders_input, "order_items": order_items_input, "payments": payments_input}
    if any("://" in location for location in (*locations.values(), output_root)):
        raise ValueError("이번 거래 입출력은 로컬 경로만 지원합니다")
    root = Path(output_root).resolve()
    for location in locations.values():
        source = Path(location).resolve()
        if source == root or source in root.parents or root in source.parents:
            raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    loaded, sources = {}, {}
    for name, location in locations.items():
        loaded[name], sources[name] = _load_jsonl(location)
    result = build_silver(loaded["orders"], loaded["order_items"], loaded["payments"])

    base = root / "silver" / "transactions"
    runs = base / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="run-", dir=runs))
    temporary = None
    try:
        paths = {}
        for name, rows in result.items():
            path = snapshot / f"{name}.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                    for row in rows), encoding="utf-8")
            paths[name] = str(path)
        manifest = {
            "status": "INCOMPLETE" if result["quarantined_records"] else "PASS",
            "check_version": CHECK_VERSION,
            "input_files": sources,
            "input_counts": {name: len(rows) for name, rows in loaded.items()},
            "output_counts": {name: len(rows) for name, rows in result.items()},
            "outputs": paths,
            "manifest_path": str(base / "current.json"),
        }
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=base,
                                         prefix=".current-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, indent=2)
        # 후속 처리는 runs/를 전부 합치지 않고 이 파일이 가리키는 결과 6개만 읽는다.
        os.replace(temporary, base / "current.json")
    except Exception:
        # 이번 실행의 고정된 파일만 제거한다. 이전 실행 결과는 건드리지 않는다.
        for name in result:
            (snapshot / f"{name}.jsonl").unlink(missing_ok=True)
        snapshot.rmdir()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="문서 기준 거래 JSONL → 로컬 Silver 결과")
    parser.add_argument("--orders-input", required=True)
    parser.add_argument("--order-items-input", required=True)
    parser.add_argument("--payments-input", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    manifest = run(args.orders_input, args.order_items_input, args.payments_input, args.output_root)
    print(f"거래 Silver {manifest['status']}: {manifest['output_counts']}")
    print(f"대표 결과: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
