from datetime import datetime, timedelta, timezone
import contextlib
import io
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import readiness
import runtime_checks as r

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


class RuntimeChecksTests(unittest.TestCase):
    def test_requests_include_init_peak_restartable_sidecars_and_overhead(self):
        pod = {"spec": {"containers": [{"resources": {"requests": {"cpu": "200m"}}}],
                        "initContainers": [
                            {"restartPolicy": "Always", "resources": {"requests": {"cpu": "50m"}}},
                            {"resources": {"requests": {"cpu": "400m"}}}],
                        "overhead": {"cpu": "10m"}}}
        self.assertEqual(r.pod_request(pod, "cpu"), 460)
        pod["spec"]["resources"] = {"requests": {"cpu": "600m"}}
        self.assertEqual(r.pod_request(pod, "cpu"), 610)

    def test_metrics_quantities_use_millicores_and_binary_memory(self):
        self.assertAlmostEqual(r.quantity("125000000n", "cpu"), 125)
        self.assertEqual(r.quantity("2", "cpu"), 2000)
        self.assertEqual(r.quantity("1048576Ki", "memory"), 1024)
        with self.assertRaises(ValueError):
            r.quantity("NaN", "cpu")

    def test_paused_or_unregistered_dags_are_waiting_not_healthy(self):
        self.assertEqual(r.dag_status(None, NOW, 900)[0], "WAITING")
        self.assertEqual(r.dag_status({"paused": True}, NOW, 900)[0], "WAITING")

    def test_running_run_does_not_hide_latest_success_age_or_failure(self):
        dag = {"paused": False, "latest": [{"state": "running"}], "last_success": (NOW - timedelta(minutes=5)).isoformat()}
        self.assertEqual(r.dag_status(dag, NOW, 900)[0], "OK")
        dag["last_success"] = (NOW - timedelta(hours=1)).isoformat()
        self.assertEqual(r.dag_status(dag, NOW, 900)[0], "WARN")
        dag["last_success"] = NOW.isoformat()
        dag["latest"] = [{"state": "failed"}]
        self.assertEqual(r.dag_status(dag, NOW, 900)[0], "WARN")

    def test_no_success_or_future_success_stays_unknown(self):
        dag = {"paused": False, "latest": [], "last_success": None}
        self.assertEqual(r.dag_status(dag, NOW, 900)[0], "UNKNOWN")
        dag["last_success"] = (NOW + timedelta(minutes=1)).isoformat()
        self.assertEqual(r.dag_status(dag, NOW, 900)[0], "UNKNOWN")

    def test_empty_error_ledger_and_unstarted_ingest_are_not_incident_alarms(self):
        def status(expected, allow_empty, complete=True):
            return r.ledger_status([], complete, NOW, 180, expected, allow_empty, readiness.object_status)[0]
        self.assertEqual(status(False, True), "INFO")
        self.assertEqual(status(False, False), "WAITING")
        self.assertEqual(status(True, False), "WARN")
        self.assertEqual(status(False, False, False), "UNKNOWN")

    def test_partial_scan_does_not_claim_freshness_absence(self):
        old = [{"LastModified": (NOW - timedelta(hours=1)).isoformat()}]
        self.assertEqual(r.ledger_status(old, False, NOW, 180, True, False, readiness.object_status)[0], "UNKNOWN")

    def test_exit_status_does_not_hide_unknown_or_waiting(self):
        def rows(*statuses):
            return [{"status": s} for s in statuses]
        self.assertEqual(r.exit_code(rows("OK", "WAITING")), 3)
        self.assertEqual(r.exit_code(rows("UNKNOWN", "WAITING")), 2)
        self.assertEqual(r.exit_code(rows("WARN", "UNKNOWN")), 1)

    def test_wrong_context_never_reaches_pipeline_exec(self):
        with patch("sys.argv", ["readiness.py", "--live", "--pipeline"]), \
                patch.object(readiness, "kube", return_value="different-context"), \
                patch.object(readiness, "aws", side_effect=RuntimeError("private failure")), \
                patch.object(r, "collect") as collect, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(readiness.main(), 2)
        collect.assert_not_called()
        self.assertNotIn("private failure", output.getvalue())

    def test_non_tokyo_bucket_is_not_scanned(self):
        calls = []
        def aws(*args):
            calls.append(args)
            if args[:2] == ("glue", "get-tables"):
                return {"TableList": []}
            return {"LocationConstraint": "ap-northeast-3"}
        args = SimpleNamespace(bucket="example", gold_b_ingest_prefix="gold-b-ingest", reprocess_dags=[],
                               node_cpu_warn_percent=90, node_memory_warn_percent=85,
                               ledger_max_age_minutes=3, dag_max_age_minutes=15, expect_ingestion=False)
        rows = r.collect(lambda *args: '{"items": []}', aws, NOW, args, readiness.object_status)
        self.assertTrue(any(row["check"] == "GoldBLedgers" and row["status"] == "UNKNOWN" for row in rows))
        self.assertFalse(any(call[:2] == ("s3api", "list-objects-v2") for call in calls))


if __name__ == "__main__":
    unittest.main()
