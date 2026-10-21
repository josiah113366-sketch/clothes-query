"""거래 Silver → Gold A 연결에서 계산 기준이 유지되는지 확인한다."""

import json
import tempfile
import unittest
from pathlib import Path

from pipelines.gold_a.transactions import build_gold
from pipelines.gold_a.transactions import run as run_gold
from pipelines.silver.transactions import build_silver
from pipelines.silver.transactions import run as run_silver


class TransactionFlowTest(unittest.TestCase):
    def test_retry_payment_and_product_totals_are_idempotent(self):
        orders = [
            {
                "order_id": "00000000-4000-8000-0000-000000000009", "member_id": "00000000-4000-8000-0000-000000000006", "session_id": "00000000-4000-8000-0000-00000000001e",
                "status": "PLACED", "status_reason": None, "total_amount": 3000,
                "ordered_at": "2026-10-14T00:30:00+09:00",
                "updated_at": "2026-10-14T00:30:00+09:00",
            },
            {
                "order_id": "00000000-4000-8000-0000-000000000009", "member_id": "00000000-4000-8000-0000-000000000006", "session_id": "00000000-4000-8000-0000-00000000001e",
                "status": "PAID", "status_reason": None, "total_amount": 3000,
                "ordered_at": "2026-10-14T00:30:00+09:00",
                "updated_at": "2026-10-14T01:10:00+09:00",
            },
        ]
        items = [
            {
                "order_item_id": "00000000-4000-8000-0000-000000000001", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "A-1",
                "quantity": 2, "unit_price": 1000,
            },
            {
                "order_item_id": "00000000-4000-8000-0000-000000000002", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "A-2",
                "quantity": 1, "unit_price": 1000,
            },
        ]
        payments = [
            {
                "payment_id": "00000000-4000-8000-0000-000000000011", "order_id": "00000000-4000-8000-0000-000000000009", "attempt_no": 1,
                "method": "CARD", "pg": "PG_A", "amount": 3000,
                "status": "FAILED", "failure_code": "PG_TIMEOUT",
                "requested_at": "2026-10-14T00:40:00+09:00",
                "completed_at": "2026-10-14T00:41:00+09:00",
            },
            {
                "payment_id": "00000000-4000-8000-0000-000000000012", "order_id": "00000000-4000-8000-0000-000000000009", "attempt_no": 2,
                "method": "CARD", "pg": "PG_A", "amount": 3000,
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

    def test_saved_silver_bundle_quality_gate_and_repeat(self):
        Path("pipelines/gold_a/.local").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir="pipelines/gold_a/.local") as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            order = {"order_id": "00000000-4000-8000-0000-000000000009", "member_id": "00000000-4000-8000-0000-000000000006", "session_id": "00000000-4000-8000-0000-00000000001e", "status": "PAID",
                     "status_reason": None, "total_amount": 2000,
                     "ordered_at": "2026-10-14T00:30:00+09:00", "updated_at": "2026-10-14T01:00:00+09:00"}
            item = {"order_item_id": "00000000-4000-8000-0000-000000000001", "order_id": "00000000-4000-8000-0000-000000000009", "article_id": "0001", "quantity": 2, "unit_price": 1000}
            payment = {"payment_id": "00000000-4000-8000-0000-000000000011", "order_id": "00000000-4000-8000-0000-000000000009", "attempt_no": 1, "method": "CARD", "pg": "PG_A",
                       "amount": 2000, "status": "SUCCESS", "failure_code": None,
                       "requested_at": "2026-10-14T00:59:00+09:00", "completed_at": "2026-10-14T01:00:00+09:00"}
            locations = {}
            for name, row in (("orders", order), ("order_items", item), ("payments", payment)):
                path = source / (name + ".jsonl")
                path.write_text(json.dumps(row) + "\n", encoding="utf-8")
                locations[name] = str(path)
            silver, gold = root / "silver", root / "gold"
            run_silver(locations["orders"], locations["order_items"], locations["payments"], str(silver))
            first = run_gold(str(silver), str(gold))
            first_rows = {name: Path(path).read_bytes() for name, path in first["outputs"].items()}
            repeated = run_gold(str(silver), str(gold))
            self.assertEqual(first_rows, {name: Path(path).read_bytes() for name, path in repeated["outputs"].items()})
            self.assertIn(b'"approved_amount": 2000', first_rows["order_sales_hourly.jsonl"])
            self.assertIn(b'"article_id": "0001"', first_rows["product_sales_daily.jsonl"])
            pointer = gold / "gold_a/transactions/current.json"
            previous = pointer.read_bytes()
            Path(locations["payments"]).write_text(json.dumps(dict(payment, amount=0)) + "\n", encoding="utf-8")
            run_silver(locations["orders"], locations["order_items"], locations["payments"], str(silver))
            with self.assertRaisesRegex(ValueError, "PASS"):
                run_gold(str(silver), str(gold))
            self.assertEqual(pointer.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
