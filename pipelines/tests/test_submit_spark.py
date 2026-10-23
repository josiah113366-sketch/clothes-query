"""제출기 exit=0이어도 Driver 실패·관찰 불능을 성공으로 처리하지 않는다."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pipelines.submit_spark import (
    TAINT,
    SubmissionError,
    check_templates,
    driver_finished,
    main,
    monitor,
)


def pod(phase, exit_code=None, *, uid="own-driver", container="spark-main"):
    result = {"metadata": {"uid": uid}, "status": {"phase": phase}}
    if exit_code is not None:
        result["status"]["containerStatuses"] = [{"name": container, "state": {
            "terminated": {"exitCode": exit_code}}}]
    return result


class Process:
    def __init__(self, code=0):
        self.code, self.stopped = code, False

    def poll(self):
        return self.code

    def terminate(self):
        self.stopped, self.code = True, -15

    def wait(self, timeout=None):
        return self.code


class Client:
    def __init__(self, *values):
        self.values, self.index = values, 0

    def read(self):
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        if isinstance(value, Exception):
            raise value
        return value


class SubmissionTest(unittest.TestCase):
    def run_monitor(self, process, client, timeout=20):
        ticks = iter(range(100))
        return monitor(process, client, timeout, sleep=lambda _: None, clock=lambda: next(ticks))

    def test_success_requires_driver_and_submitter(self):
        client = Client(None, pod("Pending"), pod("Running"), pod("Succeeded", 0))
        self.run_monitor(Process(0), client)

    def test_submitter_zero_does_not_mask_failed_driver(self):
        for value in (pod("Failed", 1), pod("Failed", 137), pod("Failed"),
                      pod("Succeeded", 7), pod("Succeeded"), pod("Succeeded", 0, container="sidecar")):
            with self.subTest(pod=value), self.assertRaises(SubmissionError):
                self.run_monitor(Process(0), Client(value))

    def test_nonzero_submitter_is_failure_even_if_driver_succeeded(self):
        with self.assertRaisesRegex(SubmissionError, "spark-submit"):
            self.run_monitor(Process(1), Client(pod("Succeeded", 0)))

    def test_cli_returns_nonzero_for_failed_driver_even_when_submitter_returns_zero(self):
        with patch("pipelines.submit_spark.check_templates"), \
                patch("pipelines.submit_spark.PodClient", return_value=Client(pod("Failed", 1))), \
                patch("pipelines.submit_spark.subprocess.Popen", return_value=Process(0)), \
                patch("pipelines.submit_spark.signal.signal"), \
                patch("sys.argv", ["submit_spark", "--namespace", "pipelines", "--", "job.py"]), \
                self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 1)

    def test_timeout_stops_submitter_without_deleting_driver(self):
        process, client = Process(None), Client(pod("Running"))
        with self.assertRaisesRegex(SubmissionError, "시간 초과"):
            self.run_monitor(process, client, timeout=3)
        self.assertTrue(process.stopped)
        self.assertFalse(hasattr(client, "cancel"))

    def test_missing_or_changed_driver_fails(self):
        for client in (Client(pod("Running"), None), Client(pod("Running"), pod("Running", uid="different")),
                       Client(None), Client(SubmissionError("API HTTP 403"))):
            with self.subTest(client=client), self.assertRaises(SubmissionError):
                self.run_monitor(Process(0), client, timeout=3)

    def test_unknown_phase_is_not_success(self):
        with self.assertRaises(SubmissionError):
            driver_finished(pod("Unknown"))

    def test_both_templates_require_dedicated_toleration(self):
        with tempfile.TemporaryDirectory() as directory:
            for role in ("driver", "executor"):
                Path(directory, role + "-pod-template.yaml").write_text(yaml.safe_dump({"spec": {
                    "tolerations": [TAINT], "containers": [{"name": "spark-main"}]}}))
            check_templates(directory)
            Path(directory, "executor-pod-template.yaml").write_text(yaml.safe_dump({"spec": {
                "containers": [{"name": "spark-main"}]}}))
            with self.assertRaisesRegex(SubmissionError, "executor"):
                check_templates(directory)


if __name__ == "__main__":
    unittest.main()
