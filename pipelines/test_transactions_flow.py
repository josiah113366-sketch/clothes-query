"""거래 Silver → Gold A 연결에서 계산 기준이 유지되는지 확인한다."""

import unittest

from pipelines.gold_a.transactions import build_gold
from pipelines.silver.transactions import build_silver


class TransactionFlowTest(unittest.TestCase):
    def test_retry_payment_and_product_totals_are_idempotent(self):
        orders = [
            {
                "order_id": "O-1", "member_id": "M-1", "session_id": "S-1",
                "status": "PLACED", "status_reason": None, "total_amount": 3000,
                "ordered_at": "2026-10-14T00:30:00+09:00",
                "updated_at": "2026-10-14T00:30:00+09:00",
            },
            {
                "order_id": "O-1", "member_id": "M-1", "session_id": "S-1",
                "status": "PAID", "status_reason": None, "total_amount": 3000,
                "ordered_at": "2026-10-14T00:30:00+09:00",
                "updated_at": "2026-10-14T01:10:00+09:00",
            },
        ]
        items = [
            {
                "order_item_id": "I-1", "order_id": "O-1", "article_id": "A-1",
                "quantity": 2, "unit_price": 1000,
            },
            {
                "order_item_id": "I-2", "order_id": "O-1", "article_id": "A-2",
                "quantity": 1, "unit_price": 1000,
            },
        ]
        payments = [
            {
                "payment_id": "P-1", "order_id": "O-1", "attempt_no": 1,
                "method": "CARD", "pg": "PG-1", "amount": 3000,
                "status": "FAILED", "failure_code": "TEMP",
                "requested_at": "2026-10-14T00:40:00+09:00",
                "completed_at": "2026-10-14T00:41:00+09:00",
            },
            {
                "payment_id": "P-2", "order_id": "O-1", "attempt_no": 2,
                "method": "CARD", "pg": "PG-1", "amount": 3000,
                "status": "SUCCESS", "failure_code": None,
                "requested_at": "2026-10-14T01:00:00+09:00",
                "completed_at": "2026-10-14T01:10:00+09:00",
            },
        ]

        silver = build_silver(orders, items, payments)
        gold = build_gold(silver)

        self.assertEqual(len(silver["orders_current"]), 1)
        self.assertEqual(len(silver["order_status_history"]), 2)
        self.assertEqual(len(silver["payment_attempts"]), 2)
        self.assertEqual(
            gold["order_sales_hourly"],
            [
                {
                    "hour_start_kst": "2026-10-14T00:00:00+09:00",
                    "order_count": 1,
                    "paid_order_count": 0,
                    "approved_amount": 0,
                },
                {
                    "hour_start_kst": "2026-10-14T01:00:00+09:00",
                    "order_count": 0,
                    "paid_order_count": 1,
                    "approved_amount": 3000,
                },
            ],
        )
        self.assertEqual(
            gold["product_sales_daily"],
            [
                {
                    "sales_date_kst": "2026-10-14", "article_id": "A-1",
                    "paid_order_count": 1, "sold_quantity": 2,
                    "item_sales_amount": 2000,
                },
                {
                    "sales_date_kst": "2026-10-14", "article_id": "A-2",
                    "paid_order_count": 1, "sold_quantity": 1,
                    "item_sales_amount": 1000,
                },
            ],
        )
        self.assertEqual(gold, build_gold(build_silver(orders, items, payments)))


if __name__ == "__main__":
    unittest.main()
