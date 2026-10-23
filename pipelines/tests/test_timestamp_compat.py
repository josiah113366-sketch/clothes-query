"""Python 3.10/3.12에서 원천 시각·지문·Silver 파싱 결과가 같아야 한다."""
import unittest
from datetime import timezone

from pipelines.format_rules import FormatRules, _aware_time
from pipelines.payment_fingerprint import FingerprintError, canonical_payment_content
from pipelines.silver.common import timestamp
from pipelines.silver.members import _timestamp as member_time
from pipelines.silver.reviews import _timestamp as review_time
from pipelines.timestamps import parse_iso_datetime


class TimestampCompatibilityTest(unittest.TestCase):
    def test_all_fraction_widths_and_offsets_preserve_microseconds(self):
        rules = FormatRules()
        for width in range(7):
            fraction = "123456"[:width]
            expected_micro = int(fraction.ljust(6, "0"))
            suffix = "." + fraction if width else ""
            results = []
            for hour, offset in ((6, "Z"), (6, "+00:00"), (15, "+09:00")):
                value = f"2026-10-21T{hour:02d}:00:02{suffix}{offset}"
                with self.subTest(width=width, offset=offset):
                    parsed = parse_iso_datetime(value).astimezone(timezone.utc)
                    self.assertEqual((parsed.hour, parsed.microsecond), (6, expected_micro))
                    for received in (_aware_time(value), timestamp({"at": value}, "at"),
                                     member_time(value, "at"), review_time(value, "at")):
                        self.assertEqual(received, parsed)
                    payment = {"payment_id": "00000000-4000-8000-0000-000000000011",
                               "order_id": "00000000-4000-8000-0000-000000000009",
                               "attempt_no": 1, "method": "CARD", "pg": "PG_A", "amount": 11800,
                               "status": "SUCCESS", "failure_code": None,
                               "requested_at": value, "completed_at": value}
                    rules.validate("payments", payment)
                    results.append(canonical_payment_content(payment))
                    padded = f"2026-10-21T06:00:02.{expected_micro:06d}Z".encode()
                    self.assertIn(padded, results[-1])
            self.assertEqual(len(set(results)), 1)

    def test_fingerprint_still_rejects_excess_precision_and_missing_timezone(self):
        payment = {"order_id": "o-1", "attempt_no": 1, "method": "CARD", "pg": "PG_A", "amount": 1,
                   "status": "SUCCESS", "requested_at": "2026-10-21T06:00:00Z",
                   "completed_at": "2026-10-21T06:00:00Z"}
        for value in ("2026-10-21T06:00:02.1234567Z", "2026-10-21T06:00:02.1",
                      "2026-13-21T06:00:02.1Z"):
            with self.subTest(value=value), self.assertRaises(FingerprintError):
                canonical_payment_content({**payment, "completed_at": value})


if __name__ == "__main__":
    unittest.main()
