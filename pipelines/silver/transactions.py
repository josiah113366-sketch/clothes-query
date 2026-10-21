"""거래 업무 행을 정상 결과·격리 기록·품질 요약으로 나눈다.

펼쳐진 CDC JSONL과 업무 행을 지원한다. S3 직접 연결·공통 YAML 실행 연결은 별도다.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from zoneinfo import ZoneInfo

from pipelines.format_rules import DEFAULT_RULES, FormatError, FormatRules

from .common import RowError as _RowError
from .common import integer as _integer
from .common import run_local
from .common import timestamp as _time

KST = ZoneInfo("Asia/Seoul")
CHECK_VERSION = "transactions.v7"
AMOUNT_CHECK_VERSION = "items-sum-v1"


def _version(raw: dict, row: dict) -> tuple:
    # source.ts_ms는 총순서가 아니다. 동시각 상충은 아래에서 보류한다.
    if "__op" in raw:
        return ("cdc", raw["__source_ts_ms"])
    return ("business", row["updated_at_utc"])


def _check_cdc(raw: dict, name: str) -> None:
    if any(field in raw for field in ("before", "after", "payload", "op")):
        raise _RowError("record", "UNSUPPORTED_CDC", "펼쳐진 CDC 행만 지원합니다")
    if "__op" not in raw:
        if any(field.startswith("__source") for field in raw):
            raise _RowError("__op", "MISSING_FIELD", "CDC 변경 종류가 없습니다")
        return
    allowed = {"r", "c", "u"} if name == "orders" else {"r", "c"}
    if raw["__op"] not in allowed:
        raise _RowError("__op", "UNSUPPORTED_CDC", "지원하지 않는 변경 또는 삭제입니다")
    _integer(raw, "__source_ts_ms", 0)
    # snapshot 필드는 실시간 행에서 null일 수 있으므로 __op=r로 판단한다.


def _order(raw: dict) -> dict:
    ordered, updated = _time(raw, "ordered_at"), _time(raw, "updated_at")
    return {
        "order_id": raw["order_id"], "member_id": raw["member_id"], "session_id": raw["session_id"],
        "status": raw["status"], "status_reason": raw.get("status_reason"),
        "total_amount": raw["total_amount"],
        "ordered_at_utc": ordered.isoformat(),
        "ordered_at_kst": ordered.astimezone(KST).isoformat(),
        "updated_at_utc": updated.isoformat(),
        "updated_at_kst": updated.astimezone(KST).isoformat(),
    }


def _item(raw: dict) -> dict:
    quantity, unit_price = raw["quantity"], raw["unit_price"]
    return {
        "order_item_id": raw["order_item_id"], "order_id": raw["order_id"], "article_id": raw["article_id"],
        "quantity": quantity, "unit_price": unit_price,
        "item_amount": quantity * unit_price,
    }


def _payment(raw: dict) -> dict:
    requested, completed = _time(raw, "requested_at"), _time(raw, "completed_at")
    return {
        "payment_id": raw["payment_id"], "order_id": raw["order_id"],
        "attempt_no": raw["attempt_no"], "method": raw["method"], "pg": raw["pg"],
        "amount": raw["amount"], "status": raw["status"], "failure_code": raw.get("failure_code"),
        "requested_at_utc": requested.isoformat(),
        "requested_at_kst": requested.astimezone(KST).isoformat(),
        "completed_at_utc": completed.isoformat(),
        "completed_at_kst": completed.astimezone(KST).isoformat(),
    }


def build_silver(
    orders: list[dict], order_items: list[dict], payments: list[dict],
    input_complete: bool = False,
    rules: FormatRules | None = None,
) -> dict[str, list[dict]]:
    """정상 상세 4개와 격리·품질 결과 반환. 입출력 실패는 호출자가 처리한다."""
    inputs = {"orders": orders, "order_items": order_items, "payments": payments}
    rules = rules if rules is not None else FormatRules()
    if not set(inputs) <= set(rules.datasets):
        raise ValueError("거래 데이터셋의 공통 규칙이 부족합니다")
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
                _check_cdc(raw, name)
                rules.validate(name, raw)
                normalized[name][index] = normalizers[name](raw)
            except (_RowError, FormatError) as exc:
                reject(name, index, exc.field, exc.code, str(exc))
                if isinstance(exc, FormatError):
                    errors[name][index]["rule_id"] = exc.rule_id

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
    seen_orders: dict[tuple, dict] = {}
    version_kinds = defaultdict(set)
    for index, row in eligible("orders"):
        version = _version(orders[index], row)
        version_kinds[row["order_id"]].add(version[0])
        marker = (row["order_id"], version)
        previous = seen_orders.setdefault(marker, row)
        if previous != row:
            reject_group("orders", row["order_id"], "updated_at", "CONTENT_CONFLICT",
                         "동일 변경 시각에 주문 내용이 다릅니다")
    for key, kinds in version_kinds.items():
        if len(kinds) > 1:
            reject_group("orders", key, "__source_ts_ms", "AMBIGUOUS_ORDER",
                         "동일 주문에 CDC 행과 업무 행이 섞여 순서를 확정할 수 없습니다")
    for name in ("order_items", "payments"):
        seen: dict[str, dict] = {}
        for _, row in eligible(name):
            key = row[keys[name]]
            previous = seen.setdefault(key, row)
            if previous != row:
                reject_group(name, key, keys[name], "CONTENT_CONFLICT", "동일 키의 업무 내용이 다릅니다")

    def unique(name: str) -> list[dict]:
        chosen = {}
        for index, row in eligible(name):
            key = ((row["order_id"], _version(inputs[name][index], row))
                   if name == "orders" else row[keys[name]])
            chosen.setdefault(key, row)
        return [chosen[key] for key in sorted(chosen)]

    by_order = defaultdict(dict)
    for index, row in eligible("orders"):
        by_order[row["order_id"]].setdefault(_version(orders[index], row), row)
    current, history = [], []
    for order_id in sorted(by_order):
        versions = sorted(by_order[order_id])
        events = [by_order[order_id][version] for version in versions]
        previous = None
        for version, row in zip(versions, events):
            if previous is None or row["status"] != previous["status"]:
                history.append({
                    "order_id": order_id,
                    "previous_status": None if previous is None else previous["status"],
                    "status": row["status"], "status_reason": row["status_reason"],
                    "changed_at_utc": row["updated_at_utc"],
                    "changed_at_kst": row["updated_at_kst"],
                })
                if version[0] == "cdc":
                    history[-1]["source_ts_ms"] = version[1]
            previous = row
        current.append({**events[-1], **({"source_ts_ms": versions[-1][1]}
                                       if versions[-1][0] == "cdc" else {})})
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

    # 주문상품을 모두 준비한 실행에서만 합계를 판정한다. 미확인 입력의 부분 합계를
    # 총액 불일치로 오인하지 않으며, 중복 상품 행은 unique()로 한 번만 더한다.
    amount_checks, blocked_orders = [], set()
    items_by_order = defaultdict(list)
    for row in unique("order_items"):
        items_by_order[row["order_id"]].append(row)
    for order in current:
        order_id = order["order_id"]
        check = {"order_id": order_id, "order_total_amount": order["total_amount"]}
        if not input_complete:
            check["status"] = "UNVERIFIED"
            amount_checks.append(check)
            continue
        item_errors = [issue for issue in errors["order_items"].values()
                       if issue["order_id"] in (None, order_id)]
        if item_errors:
            code, state, category = "DEPENDENCY_BLOCKED", "ITEM_ERROR", "DEPENDENCY_BLOCKED"
            message = "주문상품 오류 또는 연결 불명으로 합계 검사를 보류합니다"
        elif not items_by_order[order_id]:
            code, state, category = "MISSING_ORDER_ITEMS", "PENDING_REFERENCE", "PENDING_REFERENCE"
            message = "주문상품이 없어 도착 여부 확인이 필요합니다"
        else:
            total = sum(row["item_amount"] for row in items_by_order[order_id])
            check.update(item_total_amount=total, amount_difference=total - order["total_amount"])
            if total == order["total_amount"]:
                check["status"] = "PASS"
                amount_checks.append(check)
                continue
            code, state, category = "ORDER_TOTAL_MISMATCH", "MISMATCH", "INVALID"
            message = "주문상품 금액 합계와 주문 총액이 다릅니다"
        check["status"] = state
        amount_checks.append(check)
        blocked_orders.add(order_id)
        reject_group("orders", order_id, "total_amount", code, message, category)
        for index in groups["orders"][order_id]:
            errors["orders"][index].update({key: check[key] for key in (
                "order_total_amount", "item_total_amount", "amount_difference") if key in check})
    # 이미 만든 현재 상태/이력도 제거해야 후행이 잘못된 주문을 정상으로 읽지 않는다.
    current = [row for row in current if row["order_id"] not in blocked_orders]
    history = [row for row in history if row["order_id"] not in blocked_orders]
    for name in ("order_items", "payments"):
        for index, row in eligible(name):
            if row["order_id"] in blocked_orders:
                reject(name, index, "order_id", "DEPENDENCY_BLOCKED",
                       "주문 금액 검사 보류로 연결 결과를 보류합니다", "DEPENDENCY_BLOCKED")

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
            "format_rules": rules.reference(),
            "input_count": len(rows), "accepted_count": accepted,
            "quarantined_count": len(issues),
            "duplicate_count": len(rows) - len(issues) - accepted,
            "conflict_count": sum(issue["category"] == "CONFLICT" for issue in issues),
            "pending_count": sum(issue["category"] == "PENDING_REFERENCE" for issue in issues),
            "affected_order_ids": sorted({issue["order_id"] for issue in issues if issue["order_id"]}),
            "source_row_numbers": [issue["source_row_number"] for issue in issues],
            "output_counts": {key: len(output[key]) for key in destinations[name]},
        })
        if name == "orders":
            quality[-1]["amount_checks"] = amount_checks
            quality[-1]["amount_check_policy"] = AMOUNT_CHECK_VERSION + "; requires-declared-complete-input"
        elif name == "payments":
            quality[-1]["failure_code_policy"] = "format_rules:" + rules.version
    output["quarantined_records"], output["dq_results"] = quarantine, quality
    # R6용 조회 출력: 기존 검사값을 펼칠 뿐 금액을 다시 판정하지 않는다.
    # 실행 ID/검사 완료 시각/고정 참조는 저장 단계에서 연결한다.
    output["order_amount_checks"] = [
        {"order_id": check["order_id"], "check_name": "order_item_total_match",
         "check_version": AMOUNT_CHECK_VERSION, "status": check["status"],
         "order_total_amount": check["order_total_amount"],
         "item_total_amount": check.get("item_total_amount"),
         "amount_difference": check.get("amount_difference")}
        for check in amount_checks
    ]
    # 정상 결과에서 사라진 후보도 추적한다. 회원 정보·원문 대신 집계 연결 최소값만 보존.
    candidates = []
    fields = {"orders": ("order_id", "session_id", "ordered_at", "updated_at"),
              "order_items": ("order_item_id", "order_id", "article_id"),
              "payments": ("payment_id", "order_id", "status", "completed_at")}
    for name, rows in inputs.items():
        for index, raw in enumerate(rows):
            candidate = {"source_dataset": name, "source_row_number": index + 1,
                         "valid": index in normalized[name]}
            if isinstance(raw, dict):
                for field in fields[name]:
                    value = raw.get(field)
                    if isinstance(value, str) and value.strip():
                        candidate[field] = value
                if isinstance(raw.get("_input_source"), dict):
                    candidate["source"] = raw["_input_source"]
                if "__op" in raw:
                    candidate["cdc_op"] = raw["__op"]
                    candidate["source_ts_ms"] = raw.get("__source_ts_ms")
            candidates.append(candidate)
    output["impact_candidates"] = candidates
    return output


def run(orders_input: str, order_items_input: str, payments_input: str,
        output_root: str, input_complete: bool = False, rules_path: str | None = None) -> dict:
    rules = FormatRules(rules_path if rules_path is not None else DEFAULT_RULES)
    return run_local(
        {"orders": orders_input, "order_items": order_items_input, "payments": payments_input},
        output_root, "transactions", CHECK_VERSION,
        lambda rows: build_silver(rows["orders"], rows["order_items"], rows["payments"], input_complete, rules),
        input_complete=input_complete,
        rule_metadata=rules.reference(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="문서 기준 거래 JSONL → 로컬 Silver 결과")
    parser.add_argument("--orders-input", required=True)
    parser.add_argument("--order-items-input", required=True)
    parser.add_argument("--payments-input", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--input-complete", action="store_true",
                        help="필요한 전체 이력과 참조 입력을 준비했음을 실행자가 확인. 자동 입수 검증 아님")
    parser.add_argument("--rules-path", help="공통 규칙 YAML. 생략 시 저장소 docs/contracts/format_rules.yaml")
    args = parser.parse_args()
    manifest = run(args.orders_input, args.order_items_input, args.payments_input, args.output_root,
                   args.input_complete, args.rules_path)
    print(f"거래 Silver {manifest['status']}: {manifest['output_counts']}")
    print(f"대표 결과: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
