"""Silver 주문·결제·주문상품 결과로 Gold A 거래 지표를 계산한다."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import (
    exclusive_output,
    healthy_trade,
    load_products,
    load_scoped_trade,
    load_silver,
    plan_trade_holds,
    previous_gold,
    product_index,
    replacement,
    save_gold,
    save_scoped_gold,
)


def build_gold(silver: dict[str, list[dict]], products: list[dict] | None = None,
               _scoped: bool = False) -> dict[str, list[dict]]:
    """같은 Silver 입력은 언제 실행해도 같은 Gold 결과를 돌려준다."""
    checks = silver.get("dq_results")
    if not _scoped and (not checks or any(row.get("status") != "PASS" or row.get("active_error_count", row.get("quarantined_count")) != 0 for row in checks)):
        raise ValueError("Silver 품질 결과가 불완전하므로 Gold A 계산을 중단합니다")
    catalog = None if products is None else product_index(products)
    orders = {row["order_id"]: row for row in silver["orders_current"]}
    items_by_order: dict[str, list[dict]] = defaultdict(list)
    for item in silver["silver_order_items"]:
        if catalog is not None and item["article_id"] not in catalog:
            raise ValueError("판매 상품 기준정보 연결 실패")
        items_by_order[item["order_id"]].append(item)

    hourly: dict[str, dict] = {}

    def hour_bucket(at_kst: str) -> dict:
        hour_start = datetime.fromisoformat(at_kst).replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
        if hour_start not in hourly:
            hourly[hour_start] = {
                "hour_start_kst": hour_start,
                "order_count": 0,
                "paid_order_count": 0,
                "approved_amount": 0,
            }
        return hourly[hour_start]

    for order in orders.values():
        hour_bucket(order["ordered_at_kst"])["order_count"] += 1

    product_daily: dict[tuple[str, str], dict] = {}
    successful_orders = set()
    for payment in silver["payment_attempts"]:
        if payment["status"] != "SUCCESS":
            continue
        order_id = payment["order_id"]
        if order_id not in orders:
            raise ValueError("성공 결제가 연결할 주문이 없습니다")
        if order_id in successful_orders:
            raise ValueError("주문에 성공 결제가 둘 이상 있습니다")
        successful_orders.add(order_id)
        if not items_by_order[order_id]:
            raise ValueError("성공 주문의 주문상품 입력이 없습니다")
        bucket = hour_bucket(payment["completed_at_kst"])
        bucket["paid_order_count"] += 1
        bucket["approved_amount"] += payment["amount"]

        paid_date = datetime.fromisoformat(payment["completed_at_kst"]).date().isoformat()
        for item in items_by_order[order_id]:
            key = (paid_date, item["article_id"])
            if key not in product_daily:
                product_daily[key] = {
                    "sales_date_kst": paid_date,
                    "article_id": item["article_id"],
                    "paid_order_count": 0,
                    "sold_quantity": 0,
                    "item_sales_amount": 0,
                }
            row = product_daily[key]
            if catalog is not None:
                row["product_code"] = catalog[item["article_id"]]
            row["sold_quantity"] += item["quantity"]
            row["item_sales_amount"] += item["item_amount"]
            # 같은 주문에 같은 article_id의 상품 행이 여러 개여도 주문은 1건이다.
            row.setdefault("_order_ids", set()).add(order_id)

    for row in product_daily.values():
        row["paid_order_count"] = len(row.pop("_order_ids"))

    return {
        "order_sales_hourly": [hourly[key] for key in sorted(hourly)],
        "product_sales_daily": [product_daily[key] for key in sorted(product_daily)],
    }


@exclusive_output("transactions")
def run(silver_root: str, output_root: str, products_root: str | None = None,
        reprocess: dict | None = None, scope_aware: bool = False) -> dict:
    """로컬 거래 Silver 대표 묶음을 읽어 기존 두 지표를 저장한다."""
    if "://" in silver_root or "://" in output_root:
        raise ValueError("거래 Gold A 입출력은 로컬 경로만 지원합니다")
    source, target = Path(silver_root).resolve(), Path(output_root).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    base = str(target / "gold_a/transactions")
    previous = previous_gold(base)
    if previous and previous.get("status") == "PARTIAL" and not scope_aware:
        raise ValueError("보류 중인 결과는 --scope-aware와 완전한 입력으로 복구해야 합니다")
    if scope_aware:
        if reprocess:
            raise ValueError("범위별 보류 실행은 전체 입력 재계산이며 --replace 옵션과 함께 쓸 수 없습니다")
        silver, reference = load_scoped_trade(silver_root)
        products, catalog_ref = (None, None) if products_root is None else load_products(products_root)
        tables = ["order_sales_hourly", "product_sales_daily"]
        holds, affected, context = plan_trade_holds(silver, previous, tables)
        result = ({name: [] for name in tables} if any(not row["key"] for row in holds)
                  else build_gold(healthy_trade(silver, affected), products, _scoped=True))
        return save_scoped_gold(base, {name + ".jsonl": rows for name, rows in result.items()},
            {"silver_transactions": reference, "silver_products": catalog_ref}, holds, context, previous)
    manifest_uri = str(source / "silver/transactions/current.json")
    names = ["orders_current", "order_status_history", "silver_order_items", "payment_attempts", "dq_results"]
    silver, reference = load_silver(manifest_uri, {}, names)
    products, catalog_ref = (None, None) if products_root is None else load_products(products_root)
    result = build_gold(silver, products)
    return save_gold(str(target / "gold_a/transactions"),
                     {name + ".jsonl": rows for name, rows in result.items()}, {"silver_transactions": reference, "silver_products": catalog_ref}, reprocess)


def main() -> None:
    parser = argparse.ArgumentParser(description="거래 Silver 대표 결과 → Gold A 주문·상품 판매")
    parser.add_argument("--silver-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--products-root")
    parser.add_argument("--replace-start-date")
    parser.add_argument("--replace-end-date")
    parser.add_argument("--article-id", action="append")
    parser.add_argument("--scope-aware", action="store_true", help="오류 범위 보류와 정상 범위 갱신")
    args = parser.parse_args()
    scope = replacement(args.replace_start_date, args.replace_end_date, args.article_id)
    manifest = run(args.silver_root, args.output_root, args.products_root, scope, args.scope_aware)
    print("Gold A 결과·입력 품질 확인: " + manifest["manifest_path"])


if __name__ == "__main__":
    main()
