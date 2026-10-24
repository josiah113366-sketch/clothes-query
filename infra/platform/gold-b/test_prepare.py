import copy
import unittest
import yaml

from prepare import foundation, pending_ingest, pending_runtime, shared_spark_conf, workload_bindings


class GoldBPreparationTest(unittest.TestCase):
    def test_preserves_live_bindings_and_rejects_overwrite(self):
        original = {"bindings": {"existing": {"namespace": "kafka", "service_account": "connect", "s3_access": {"bronze/": ["s3:PutObject"]}}}}
        before = copy.deepcopy(original)
        new = workload_bindings(original)
        self.assertEqual(original, before)
        self.assertEqual(new["bindings"]["existing"], before["bindings"]["existing"])
        new["bindings"]["gold-b-ledger-jobs"]["s3_access"]["ground_truth/"] = ["s3:GetObject"]
        with self.assertRaises(ValueError):
            workload_bindings(new)

    def test_separates_ingestion_from_destructive_ledger_maintenance(self):
        bindings = workload_bindings({})["bindings"]
        ingest = bindings["gold-b-ingest-driver"]["s3_access"]
        self.assertEqual(set(ingest), {"gold_b/payment_events/", "gold_b/topic_messages/", "gold_b/malformed_events/"})
        self.assertTrue(all(set(actions) == {"s3:GetObject", "s3:PutObject"} for actions in ingest.values()))
        jobs = bindings["gold-b-ledger-jobs"]["s3_access"]
        self.assertNotIn("s3:DeleteObject", jobs["gold_b/reprocess_events/"])
        self.assertEqual({p for p, actions in jobs.items() if "s3:DeleteObject" in actions}, {
            "gold_b/payment_events/", "gold_b/topic_messages/", "gold_b/malformed_events/", "gold_b/bronze_lag_snapshots/"})
        self.assertTrue(all(actions == ["s3:GetObject"] for p, actions in jobs.items() if p.startswith("bronze_v2/")))
        self.assertFalse(any(p.startswith(("ground_truth/", "agent/", "silver/", "gold_a/")) for b in bindings.values() for p in b["s3_access"]))

    def test_checkpoint_requires_explicit_narrow_prefix(self):
        for bad in ["gold_b/", "ground_truth/", "gold_b/_checkpoints/*/", "gold_b/_checkpoints/../"]:
            with self.subTest(prefix=bad), self.assertRaises(ValueError):
                workload_bindings({}, bad)
            with self.subTest(runtime_prefix=bad), self.assertRaises(ValueError):
                pending_ingest(bad)
        p = "gold_b/_checkpoints/streaming_ingest/"
        self.assertIsNone(pending_ingest()["env"]["GOLD_B_CHECKPOINT"])
        self.assertEqual(pending_ingest(p)["env"]["GOLD_B_CHECKPOINT"],
                         "s3a://clothes-query-datalake/" + p)
        bindings = workload_bindings({}, p)["bindings"]
        self.assertIn("s3:DeleteObject", bindings["gold-b-ingest-driver"]["s3_access"][p])
        self.assertNotIn(p, bindings["gold-b-ledger-jobs"]["s3_access"])
        existing = workload_bindings({})
        self.assertEqual(workload_bindings(existing, p)["bindings"], bindings)

    def test_preparation_does_not_launch_or_take_over_shared_namespace(self):
        objects = foundation()
        self.assertFalse(any(o["kind"] in {"Pod", "Job", "Deployment", "Namespace", "ResourceQuota", "NodePool", "Secret"} for o in objects))
        cm = next(o for o in objects if o["kind"] == "ConfigMap")
        for role in ("driver", "executor"):
            spec = yaml.safe_load(cm["data"][role + "-pod-template.yaml"])["spec"]
            self.assertEqual(spec["serviceAccountName"], "gold-b-ingest-" + role)
            self.assertEqual(spec["nodeSelector"]["karpenter.sh/nodepool"], "clothes-query-dev-compute-spark")
            self.assertEqual(spec["tolerations"][0]["value"], "spark")
            self.assertEqual(spec["securityContext"]["fsGroup"], 185)
            self.assertTrue(any(v.get("secret", {}).get("secretName") == "gold-b-ingest-tls" for v in spec["volumes"]))

    def test_kafka_access_does_not_grant_write_or_cluster_admin(self):
        users = [o for o in foundation() if o["kind"] == "KafkaUser"]
        self.assertEqual(len(users), 2)
        for user in users:
            for acl in user["spec"]["authorization"]["acls"]:
                self.assertLessEqual(set(acl["operations"]), {"Read", "Describe"})
                self.assertIn(acl["resource"]["type"], {"topic", "group"})
                if acl["resource"]["type"] == "group":
                    self.assertEqual(acl["resource"]["name"], user["metadata"]["name"] + "-")

    def test_pending_image_cannot_be_mistaken_for_deployable_runtime(self):
        self.assertIsNone(pending_runtime()["image"])
        self.assertEqual(pending_runtime()["pool"], "gold_b_ledger")
        self.assertNotIn("checkpoint", pending_runtime())

    def test_single_node_cpu_budget_and_executor_cap(self):
        ingest, batch = [shared_spark_conf(r) for r in ("ingest", "batch")]
        total = sum(float(c[k]) for c in (ingest, batch) for k in (
            "spark.kubernetes.driver.request.cores", "spark.kubernetes.executor.request.cores")) + 0.1
        self.assertLessEqual(total, 1.78)
        for conf in (ingest, batch):
            self.assertEqual(conf["spark.dynamicAllocation.enabled"], "false")
            self.assertEqual(conf["spark.dynamicAllocation.maxExecutors"], "1")


if __name__ == "__main__":
    unittest.main()
