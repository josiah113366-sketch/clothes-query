"""전체 Silver 이력에서 세션·상품 퍼널과 첫 조회일 기준 전환율을 만든다."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from . import load_silver, load_products, product_index, require_pass, save_gold, _uri, replacement
from .reviews import ratio

KST = ZoneInfo("Asia/Seoul")


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("퍼널 시각에는 시간대가 필요합니다")
    return parsed.astimezone(KST)


def build_funnels(clicks: dict, transactions: dict, products: list[dict]) -> dict[str, list[dict]]:
    require_pass(clicks)
    require_pass(transactions)
    catalog = product_index(products)
    events = defaultdict(lambda: {"view": [], "cart_add": []})
    seen = set()
    for event in clicks["click_events"]:
        if event["event_id"] in seen:
            raise ValueError("Silver 클릭 event_id 중복")
        seen.add(event["event_id"])
        article, session = event["article_id"], event["session_id"]
        if article not in catalog or not isinstance(session, str) or not session.strip():
            raise ValueError("클릭의 상품 또는 세션 연결 오류")
        if event["event_type"] not in {"view", "cart_add"}:
            raise ValueError("퍼널에서 지원하지 않는 이벤트")
        events[(session, article)][event["event_type"]].append(_time(event["event_time_kst"]))
    orders = {row["order_id"]: row for row in transactions["orders_current"]}
    if len(orders) != len(transactions["orders_current"]):
        raise ValueError("Silver 주문 ID 중복")
    articles_by_order = defaultdict(set)
    for item in transactions["silver_order_items"]:
        if item["order_id"] not in orders or item["article_id"] not in catalog:
            raise ValueError("주문상품의 주문 또는 상품 연결 오류")
        articles_by_order[item["order_id"]].add(item["article_id"])
    paid = {}
    for payment in transactions["payment_attempts"]:
        if payment["order_id"] not in orders:
            raise ValueError("결제의 주문 연결 오류")
        if payment["status"] == "SUCCESS":
            order_id = payment["order_id"]
            completed = _time(payment["completed_at_kst"])
            if order_id in paid or completed < _time(orders[order_id]["ordered_at_kst"]):
                raise ValueError("성공 결제 중복 또는 주문보다 빠른 결제 시각")
            paid[order_id] = completed
    linked = defaultdict(list)
    for order_id, order in orders.items():
        for article in articles_by_order[order_id]:
            linked[(order["session_id"], article)].append((order_id, _time(order["ordered_at_kst"])))
    detail = []
    for (session, article), steps in sorted(events.items()):
        if not steps["view"]:
            continue
        first_view = min(steps["view"])
        carts = sorted(at for at in steps["cart_add"] if at >= first_view)
        attempts = [(key, at) for key, at in linked[(session, article)] if at >= first_view]
        successful = [paid[key] for key, _ in attempts if key in paid]
        first_cart = min(carts) if carts else None
        first_order = min((at for _, at in attempts), default=None)
        first_paid = min(successful, default=None)
        detail.append({"session_id": session, "article_id": article, "product_code": catalog[article],
            "first_view_at_kst": first_view.isoformat(),
            "first_cart_at_kst": first_cart.isoformat() if first_cart else None,
            "first_order_at_kst": first_order.isoformat() if first_order else None,
            "first_paid_at_kst": first_paid.isoformat() if first_paid else None,
            "has_view": True, "has_cart": bool(carts), "has_order": bool(attempts), "has_paid": bool(successful),
            "ordered_after_cart": any(first_cart is not None and at >= first_cart for _, at in attempts)})
    daily = {}
    for row in detail:
        key = (row["first_view_at_kst"][:10], row["article_id"])
        bucket = daily.setdefault(key, {"funnel_date_kst": key[0], "article_id": key[1],
            "product_code": row["product_code"], "view_sessions": 0, "cart_sessions": 0,
            "order_sessions": 0, "paid_sessions": 0, "cart_order_sessions": 0})
        for field, flag in (("view_sessions", "has_view"), ("cart_sessions", "has_cart"),
                            ("order_sessions", "has_order"), ("paid_sessions", "has_paid"),
                            ("cart_order_sessions", "ordered_after_cart")):
            bucket[field] += int(row[flag])
    for row in daily.values():
        for name, numerator, denominator in (
            ("view_to_cart_rate", "cart_sessions", "view_sessions"),
            ("view_to_order_rate", "order_sessions", "view_sessions"),
            ("view_to_paid_rate", "paid_sessions", "view_sessions"),
            ("cart_to_order_rate", "cart_order_sessions", "cart_sessions"),
            ("order_to_paid_rate", "paid_sessions", "order_sessions")):
            row[name] = ratio(row[numerator], row[denominator])
    return {"funnel_session_product": detail, "funnel_daily": [daily[key] for key in sorted(daily)]}


def run(clicks_root: str, transactions_root: str, products_root: str, output_root: str,
        reprocess: dict | None = None) -> dict:
    clicks, click_ref = load_silver(_uri(clicks_root, "silver", "clicks", "current.json"), {}, ["click_events", "dq_results"])
    trade, trade_ref = load_silver(_uri(transactions_root, "silver", "transactions", "current.json"), {},
                                  ["orders_current", "silver_order_items", "payment_attempts", "dq_results"])
    products, catalog_ref = load_products(products_root)
    result = build_funnels(clicks, trade, products)
    return save_gold(_uri(output_root, "gold_a", "funnels"),
                     {name + ".jsonl": rows for name, rows in result.items()},
                     {"silver_clicks": click_ref, "silver_transactions": trade_ref, "silver_products": catalog_ref,
                      "cohort_policy": "first-view-kst; same-session-product; entire-supplied-history; no-cutoff"}, reprocess)


def main():
    parser = argparse.ArgumentParser(description="Silver → 세션·상품 퍼널 및 일별 전환율")
    for option in ("clicks-root", "transactions-root", "products-root", "output-root"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--replace-start-date")
    parser.add_argument("--replace-end-date")
    parser.add_argument("--article-id", action="append")
    args = parser.parse_args()
    scope = replacement(args.replace_start_date, args.replace_end_date, args.article_id)
    result = run(args.clicks_root, args.transactions_root, args.products_root, args.output_root, scope)
    print("퍼널 결과: " + result["manifest_path"])


if __name__ == "__main__":
    main()
