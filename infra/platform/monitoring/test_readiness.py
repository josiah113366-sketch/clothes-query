from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import readiness as r

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


class ReadinessTests(unittest.TestCase):
    def test_missing_stale_future_and_nan_metrics_are_unknown(self):
        for points in [[], [{"Timestamp": (NOW - timedelta(hours=1)).isoformat(), "Maximum": 0}],
                       [{"Timestamp": (NOW + timedelta(minutes=1)).isoformat(), "Maximum": 0}],
                       [{"Timestamp": NOW.isoformat(), "Maximum": float("nan")}]]:
            with self.subTest(points=points):
                self.assertEqual(r.point_status(points, "Maximum", 100, NOW)[0], "UNKNOWN")

    def test_wal_warning_and_free_space_warning_have_opposite_directions(self):
        point = [{"Timestamp": NOW.isoformat(), "Maximum": 100, "Minimum": 100}]
        self.assertEqual(r.point_status(point, "Maximum", 80, NOW), ("WARN", 100))
        self.assertEqual(r.point_status(point, "Minimum", 80, NOW, below=True), ("OK", 100))

    def test_object_scan_limit_does_not_become_false_absence_alarm(self):
        old = [{"LastModified": (NOW - timedelta(hours=2)).isoformat()}]
        self.assertEqual(r.object_status(old, False, NOW, 1800)[0], "UNKNOWN")
        self.assertEqual(r.object_status(old, True, NOW, 1800)[0], "WARN")
        self.assertEqual(r.object_status([], False, NOW, 1800)[0], "UNKNOWN")

    def test_recent_object_proves_arrival_even_when_scan_is_incomplete(self):
        objects = [{"LastModified": (NOW - timedelta(minutes=1)).isoformat()}]
        self.assertEqual(r.object_status(objects, False, NOW, 1800), ("OK", 60))

    def test_kubernetes_flags_precede_exec_command(self):
        with patch.object(r, "command", return_value="") as call:
            r.kube("exec", "pod", "--", "df", "-Pk", "/var/lib/kafka/data-0")
        argv = call.call_args.args[0]
        self.assertLess(argv.index("--request-timeout=20s"), argv.index("--"))
        self.assertEqual(argv[-3:], ["df", "-Pk", "/var/lib/kafka/data-0"])


if __name__ == "__main__":
    unittest.main()
