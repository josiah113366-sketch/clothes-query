import json
from pathlib import Path
import unittest

import runtime
import yaml


class RuntimeSafetyTests(unittest.TestCase):
    def test_default_contains_no_workload_or_billable_capacity(self):
        objects = runtime.resources()
        self.assertFalse({"Job", "Pod", "NodePool", "Application", "Deployment"} & {x["kind"] for x in objects})
        self.assertTrue(all(x["metadata"].get("namespace", "spark") == "spark" for x in objects))

    def test_driver_and_executor_placement_match_selected_pool(self):
        for placement, pool in [("dedicated", "clothes-query-dev-compute-spark"), ("shared-memory", "clothes-query-dev-compute")]:
            for name in ["driver", "executor"]:
                spec = runtime.pod_template(name, placement)["spec"]
                self.assertEqual(spec["nodeSelector"]["karpenter.sh/nodepool"], pool)
                self.assertEqual(bool(spec.get("tolerations")), placement == "dedicated")
                self.assertEqual(spec["automountServiceAccountToken"], name == "driver")

    def test_job_requires_digest_and_image_local_entry(self):
        image = "example.invalid/spark@sha256:" + "a" * 64
        job = runtime.submission_job(image, "local:///opt/jobs/main.py", "small-trial", "dedicated")
        self.assertEqual(job["spec"]["template"]["spec"]["serviceAccountName"], "spark-submitter")
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        custom = runtime.submission_job(image, "local:///opt/jobs/main.py", "small-trial", "dedicated", ["--input", "s3://example/input/"])
        self.assertEqual(custom["spec"]["template"]["spec"]["containers"][0]["args"][-2:], ["--input", "s3://example/input/"])
        for bad_image, bad_path in [("spark:latest", "local:///opt/jobs/main.py"), (image, "s3://bucket/job.py"), (image, "local:///opt/../secret.py")]:
            with self.assertRaises(ValueError):
                runtime.submission_job(bad_image, bad_path, "small-trial", "dedicated")

    def test_permissions_do_not_grant_secret_or_cluster_management(self):
        for obj in runtime.resources():
            for rule in obj.get("rules", []):
                self.assertFalse(set(rule["resources"]) & {"secrets", "roles", "rolebindings", "serviceaccounts", "*"})
                self.assertNotIn("*", rule["verbs"])

    def test_default_executor_count_is_bounded(self):
        for placement in ["dedicated", "shared-memory"]:
            conf = dict(line.split(maxsplit=1) for line in runtime.properties(placement).splitlines())
            self.assertEqual(conf["spark.executor.instances"], "1")
            self.assertEqual(conf["spark.dynamicAllocation.enabled"], "false")
            objects = runtime.resources(placement)
            cm = next(x for x in objects if x["kind"] == "ConfigMap")
            self.assertIn("spec", yaml.safe_load(cm["data"]["executor-pod-template.yaml"]))

    def test_shared_cpu_math_includes_the_waiting_submitter(self):
        sizing = yaml.safe_load((Path(__file__).parent / "cpu-sizing-candidates.yaml").read_text())
        saved = sum(v["current_m"] - v["candidate_m"] for v in sizing["candidates"].values())
        spark = sum(sizing["shared_spark_requests_m"].values())
        self.assertEqual(saved, 765)
        self.assertEqual(spark, 700)
        self.assertGreater(sizing["current_requests_m"] + spark, sizing["common_cpu_allocatable_m_estimate"])
        self.assertLess(sizing["current_requests_m"] - saved + spark, sizing["common_cpu_allocatable_m_estimate"])
        conf = dict(line.split(maxsplit=1) for line in runtime.properties("shared-memory").splitlines())
        self.assertEqual(conf["spark.kubernetes.driver.request.cores"], "100m")
        self.assertEqual(conf["spark.kubernetes.executor.request.cores"], "500m")
        job = runtime.submission_job("example.invalid/spark@sha256:" + "a" * 64, "local:///opt/jobs/main.py", "shared-trial", "shared-memory")
        self.assertEqual(job["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["cpu"], "100m")

    def test_shared_deployment_config_keeps_spark_capacity_disabled(self):
        path = Path(__file__).resolve().parents[2] / "stacks/compute/deployment.auto.tfvars.json"
        self.assertIs(json.loads(path.read_text())["spark_node_pool"]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
