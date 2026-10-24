"""실제 Airflow 이미지에서 DAG 구조·실패 전파·공개 Pod를 검증한다. DB/클러스터 접속 없음."""
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

try:
    from airflow.dag_processing.dagbag import DagBag
    from kubernetes.client import ApiClient
except ImportError as error:
    raise unittest.SkipTest("Airflow 이미지에서 실행하는 DAG 검증입니다") from error


class PublicationDagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = {"image": "example.invalid/pipelines@sha256:" + "1" * 64, "namespace": "pipelines",
                  "submitter_service_account": "silver-gold-a-submitter",
                  "driver_service_account": "silver-gold-a-driver",
                  "executor_service_account": "silver-gold-a-executor", "silver_database": "silver"}
        path = Path(__file__).resolve().parents[2] / "infra/platform/airflow/dags/silver_gold_a.py"
        with patch.dict(os.environ, {"AIRFLOW_PIPELINE_RUNTIME": json.dumps(config)}):
            bag = DagBag(dag_folder=str(path))
        assert not bag.import_errors, bag.import_errors
        cls.dag = bag.dags["silver_gold_a_batch"]

    def test_publication_does_not_mask_spark_failure(self):
        tasks = self.dag.task_dict
        self.assertEqual(set(tasks), {"check_request", "submit_spark", "publish_r6", "report_failure"})
        self.assertEqual(tasks["publish_r6"].trigger_rule, "all_done")
        self.assertEqual(tasks["report_failure"].trigger_rule, "one_failed")
        self.assertEqual(tasks["report_failure"].upstream_task_ids,
                         {"check_request", "submit_spark", "publish_r6"})
        self.assertEqual({t.task_id for t in tasks.values() if not t.downstream_task_ids}, {"report_failure"})
        self.assertEqual(self.dag.max_active_runs, 1)
        with self.assertRaises(RuntimeError):
            tasks["report_failure"].python_callable()

    def test_publisher_uses_driver_identity_without_spark(self):
        operator = self.dag.get_task("publish_r6")
        with patch.object(type(operator), "hook", new_callable=PropertyMock) as hook:
            hook.return_value = SimpleNamespace(is_in_cluster=True)
            pod = ApiClient().sanitize_for_serialization(operator.build_pod_request_obj())
        spec = pod["spec"]
        self.assertEqual(spec["serviceAccountName"], "silver-gold-a-driver")
        self.assertEqual(spec["nodeSelector"], {"karpenter.sh/nodepool": "clothes-query-dev-compute-spark"})
        self.assertIn({"effect": "NoSchedule", "key": "clothes-query/dedicated", "operator": "Equal", "value": "spark"},
                      spec["tolerations"])
        container = spec["containers"][0]
        self.assertEqual(container["command"], ["python3", "-m", "pipelines.r6_publication"])
        self.assertEqual(container["args"][-2:], ["--database", "silver"])
        self.assertIn("dag_run.conf", container["args"][1])
        self.assertEqual(container["resources"]["limits"]["memory"], "1Gi")


if __name__ == "__main__":
    unittest.main()
