"""Silver 주문·결제·주문상품 결과로 Gold A 거래 지표를 계산한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import _uri, load_silver, save_gold

from collections import defaultdict
from datetime import datetime


def build_gold(silver: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """같은 Silver 입력은 언제 실행해도 같은 Gold 결과를 돌려준다."""
    checks = silver.get("dq_results")
    if not checks or any(row.get("status") != "PASS" or row.get("quarantined_count") != 0 for row in checks):
        raise ValueError("Silver 품질 결과가 불완전하므로 Gold A 계산을 중단합니다")
    orders = {row["order_id"]: row for row in silver["orders_current"]}
    items_by_order: dict[str, list[dict]] = defaultdict(list)
    for item in silver["silver_order_items"]:
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
    for payment in silver["payment_attempts"]:
        if payment["status"] != "SUCCESS":
            continue
        order_id = payment["order_id"]
        if order_id not in orders:
            raise ValueError("성공 결제가 연결할 주문이 없습니다")
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


def run(silver_root: str, output_root: str) -> dict:
    """로컬 거래 Silver 대표 묶음을 읽어 기존 두 지표를 저장한다."""
    if "://" in silver_root or "://" in output_root:
        raise ValueError("거래 Gold A 입출력은 로컬 경로만 지원합니다")
    source, target = Path(silver_root).resolve(), Path(output_root).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    manifest_uri = str(source / "silver/transactions/current.json")
    names = ["orders_current", "order_status_history", "silver_order_items", "payment_attempts", "dq_results"]
    silver, reference = load_silver(manifest_uri, {}, names)
    result = build_gold(silver)
    return save_gold(str(target / "gold_a/transactions"),
                     {name + ".jsonl": rows for name, rows in result.items()}, {"silver_transactions": reference})


def main() -> None:
    parser = argparse.ArgumentParser(description="거래 Silver 대표 결과 → Gold A 주문·상품 판매")
    parser.add_argument("--silver-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    manifest = run(args.silver_root, args.output_root)
    print("Gold A 결과·입력 품질 확인: " + manifest["manifest_path"])


if __name__ == "__main__":
    main()
