"""전체 Silver 이력에서 세션·상품 퍼널과 첫 조회일 기준 전환율을 만든다."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from . import (
    _read_text,
    _uri,
    exclusive_output,
    healthy_trade,
    load_products,
    load_scoped_trade,
    load_silver,
    plan_trade_holds,
    previous_gold,
    product_index,
    replacement,
    require_pass,
    save_gold,
    save_scoped_gold,
)
from .reviews import ratio

KST = ZoneInfo("Asia/Seoul")


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("퍼널 시각에는 시간대가 필요합니다")
    return parsed.astimezone(KST)


def build_funnels(clicks: dict, transactions: dict, products: list[dict],
                  _scoped: bool = False) -> dict[str, list[dict]]:
    require_pass(clicks)
    if not _scoped:
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


@exclusive_output("funnels")
def run(clicks_root: str, transactions_root: str, products_root: str, output_root: str,
        reprocess: dict | None = None, scope_aware: bool = False) -> dict:
    clicks, click_ref = load_silver(_uri(clicks_root, "silver", "clicks", "current.json"), {}, ["click_events", "dq_results"])
    base = _uri(output_root, "gold_a", "funnels")
    previous = previous_gold(base) if not output_root.startswith("s3://") else None
    if previous and previous.get("status") == "PARTIAL" and not scope_aware:
        raise ValueError("보류 중인 퍼널은 --scope-aware와 완전한 입력으로 복구해야 합니다")
    if scope_aware:
        if reprocess or any("://" in root for root in (clicks_root, transactions_root, products_root, output_root)):
            raise ValueError("범위별 퍼널은 로컬 전체 입력만 지원하며 --replace 옵션과 함께 쓸 수 없습니다")
        click_manifest = json.loads(_read_text(_uri(clicks_root, "silver", "clicks", "current.json")))
        if click_manifest.get("input_completeness") != "DECLARED_COMPLETE":
            raise ValueError("퍼널 범위별 갱신에는 클릭 Silver --input-complete 확인도 필요합니다")
        trade, trade_ref = load_scoped_trade(transactions_root)
        products, catalog_ref = load_products(products_root)
        tables = ["funnel_session_product", "funnel_daily"]
        holds, affected, context = plan_trade_holds(trade, previous, tables, clicks["click_events"])
        result = ({name: [] for name in tables} if any(not row["key"] for row in holds)
                  else build_funnels(clicks, healthy_trade(trade, affected), products, _scoped=True))
        return save_scoped_gold(base, {name + ".jsonl": rows for name, rows in result.items()},
            {"silver_transactions": trade_ref, "silver_clicks": click_ref, "silver_products": catalog_ref},
            holds, context, previous)
    trade, trade_ref = load_silver(_uri(transactions_root, "silver", "transactions", "current.json"), {},
                                  ["orders_current", "silver_order_items", "payment_attempts", "dq_results"])
    products, catalog_ref = load_products(products_root)
    result = build_funnels(clicks, trade, products)
    return save_gold(_uri(output_root, "gold_a", "funnels"),
                     {name + ".jsonl": rows for name, rows in result.items()},
                     {"silver_clicks": click_ref, "silver_transactions": trade_ref, "silver_products": catalog_ref,
                      "cohort_policy": "first-view-kst; same-session-product; entire-supplied-history; no-cutoff"}, reprocess)


def build_funnels_spark(clicks, transactions, catalog, *, _scoped=False):
    """전체 입력 이력에서 기존 첫 조회·같은 세션/상품 규칙을 Spark SQL로 계산한다."""
    from pyspark.sql import functions as F

    for tables in (() if _scoped else (clicks, transactions)):
        if tables["dq_results"].filter("status != 'PASS' or quarantined_count > 0").limit(1).count():
            raise ValueError("퍼널 입력 Silver 품질이 불완전합니다")
    events = clicks["click_events"]
    orders, items, payments = (transactions[k] for k in ("orders_current", "silver_order_items", "payment_attempts"))
    variants = catalog["silver_product_variant"].select("article_id", "product_code")
    if events.groupBy("event_id").count().filter("count > 1").limit(1).count():
        raise ValueError("Silver 클릭 event_id 중복")
    if orders.groupBy("order_id").count().filter("count > 1").limit(1).count():
        raise ValueError("Silver 주문 ID 중복")
    if events.filter("session_id is null or trim(session_id) = '' or event_type not in ('view','cart_add')").limit(1).count():
        raise ValueError("클릭의 세션 또는 이벤트 오류")
    if events.join(variants, "article_id", "left_anti").limit(1).count():
        raise ValueError("클릭의 상품 연결 오류")
    if (items.join(orders.select("order_id"), "order_id", "left_anti").limit(1).count()
            or items.join(variants, "article_id", "left_anti").limit(1).count()):
        raise ValueError("주문상품의 주문 또는 상품 연결 오류")
    if payments.join(orders.select("order_id"), "order_id", "left_anti").limit(1).count():
        raise ValueError("결제의 주문 연결 오류")
    paid = payments.filter("status = 'SUCCESS'").select("order_id", F.to_timestamp("completed_at_utc").alias("paid_at"))
    if paid.groupBy("order_id").count().filter("count > 1").limit(1).count():
        raise ValueError("성공 결제 중복")
    if paid.join(orders, "order_id").filter(F.col("paid_at") < F.to_timestamp("ordered_at_utc")).limit(1).count():
        raise ValueError("주문보다 빠른 성공 결제 시각")
    events = events.withColumn("event_at", F.to_timestamp("event_time_utc"))
    keys = ["session_id", "article_id"]
    views = events.filter("event_type = 'view'").groupBy(*keys).agg(F.min("event_at").alias("view_at"))
    carts = events.filter("event_type = 'cart_add'").join(views, keys).filter("event_at >= view_at").groupBy(*keys).agg(
        F.min("event_at").alias("cart_at"))
    steps = views.join(carts, keys, "left")
    attempts = orders.join(items.select("order_id", "article_id").dropDuplicates(), "order_id").select(
        "order_id", "session_id", "article_id", F.to_timestamp("ordered_at_utc").alias("order_at"))
    attempts = attempts.join(steps, keys).filter("order_at >= view_at").join(paid, "order_id", "left")
    reached = attempts.groupBy(*keys).agg(F.min("order_at").alias("order_at"), F.min("paid_at").alias("paid_at"),
        F.max(F.when(F.col("cart_at").isNotNull() & (F.col("order_at") >= F.col("cart_at")), 1).otherwise(0)).alias("after_cart"))
    detail = steps.join(reached, keys, "left").join(variants, "article_id").withColumn("has_view", F.lit(True))
    for flag, at in (("has_cart", "cart_at"), ("has_order", "order_at"), ("has_paid", "paid_at")):
        detail = detail.withColumn(flag, F.col(at).isNotNull())
    detail = detail.withColumn("ordered_after_cart", F.coalesce(F.col("after_cart") > 0, F.lit(False)))

    def iso_kst(field):
        at = F.from_utc_timestamp(F.col(field), "Asia/Seoul")
        fraction = F.date_format(at, "SSSSSS")
        return F.concat(F.date_format(at, "yyyy-MM-dd'T'HH:mm:ss"),
                        F.when(fraction != "000000", F.concat(F.lit("."), fraction)).otherwise(F.lit("")), F.lit("+09:00"))

    detail = detail.select("session_id", "article_id", "product_code",
        *[iso_kst(at).alias(name) for name, at in (("first_view_at_kst", "view_at"), ("first_cart_at_kst", "cart_at"),
                                                  ("first_order_at_kst", "order_at"), ("first_paid_at_kst", "paid_at"))],
        "has_view", "has_cart", "has_order", "has_paid", "ordered_after_cart")
    metrics = (("view_sessions", "has_view"), ("cart_sessions", "has_cart"), ("order_sessions", "has_order"),
               ("paid_sessions", "has_paid"), ("cart_order_sessions", "ordered_after_cart"))
    daily = detail.groupBy(F.to_date(F.substring("first_view_at_kst", 1, 10)).alias("funnel_date_kst"),
                           "article_id", "product_code").agg(*[F.sum(F.col(flag).cast("long")).alias(name) for name, flag in metrics])
    for name, numerator, denominator in (
        ("view_to_cart_rate", "cart_sessions", "view_sessions"), ("view_to_order_rate", "order_sessions", "view_sessions"),
        ("view_to_paid_rate", "paid_sessions", "view_sessions"), ("cart_to_order_rate", "cart_order_sessions", "cart_sessions"),
        ("order_to_paid_rate", "paid_sessions", "order_sessions")):
        daily = daily.withColumn(name, F.when(F.col(denominator) > 0, F.round(
            F.col(numerator).cast("decimal(30,0)") / F.col(denominator), 6)).cast("double"))
    return {"funnel_session_product": detail, "funnel_daily": daily}


def main():
    parser = argparse.ArgumentParser(description="Silver → 세션·상품 퍼널 및 일별 전환율")
    for option in ("clicks-root", "transactions-root", "products-root", "output-root"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--replace-start-date")
    parser.add_argument("--replace-end-date")
    parser.add_argument("--article-id", action="append")
    parser.add_argument("--scope-aware", action="store_true", help="거래 오류의 퍼널 영향 범위만 갱신 보류")
    args = parser.parse_args()
    scope = replacement(args.replace_start_date, args.replace_end_date, args.article_id)
    result = run(args.clicks_root, args.transactions_root, args.products_root, args.output_root, scope, args.scope_aware)
    print("퍼널 결과: " + result["manifest_path"])


if __name__ == "__main__":
    main()
