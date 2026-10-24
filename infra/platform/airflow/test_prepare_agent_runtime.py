"""Verify deployment configuration boundaries and existing bundle preservation."""
import copy
import json
from pathlib import Path
import unittest

import yaml

from prepare_agent_runtime import render


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.base = yaml.safe_load(Path(__file__).with_name("development-values.yaml").read_text(encoding="utf-8"))
        # The live Git bundle is a deployment overlay, absent from initial chart examples.
        self.base.setdefault("dagProcessor", {})["dagBundleConfigList"] = [{
            "name": "dags-folder", "classpath": "airflow.providers.git.bundles.git.GitDagBundle",
            "kwargs": {"subdir": "infra/platform/airflow/dags", "tracking_ref": "main"}}]
        self.config = {"detect_image": "827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/detection-job@sha256:" + "a" * 64,
                       "investigate_image": "827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/investigation-agent@sha256:" + "b" * 64,
                       "detect_workgroup": "detection-test", "investigate_workgroup": "investigation-test",
                       "region": "ap-northeast-1", "bedrock_model_id": "jp.anthropic.claude-haiku-4-5-20251001-v1:0"}

    def test_preserves_existing_environment_and_bundle(self):
        old = copy.deepcopy(self.base)
        cm, values = render(self.config, self.base)
        self.assertEqual(self.base, old)
        self.assertEqual(values["dagProcessor"]["dagBundleConfigList"][:-1], old["dagProcessor"]["dagBundleConfigList"])
        self.assertEqual(yaml.safe_load(values["extraEnv"])[:-1], yaml.safe_load(old["extraEnv"]))
        self.assertEqual(cm["metadata"]["namespace"], "airflow")
        self.assertEqual(json.loads(cm["data"]["config"])["investigate_max"], 3)
        self.assertNotIn("hostname", json.loads(cm["data"]["config"]))
        self.assertEqual(values["config"]["core"]["dags_are_paused_at_creation"], "True")
        self.assertNotIn("parallelism", values["config"]["core"])

    def test_rejects_tags_wrong_accounts_and_swapped_repositories(self):
        for image in ["image:latest", self.config["detect_image"].replace("827913617635", "000000000000"), self.config["investigate_image"]]:
            with self.subTest(image=image), self.assertRaises(ValueError):
                render(dict(self.config, detect_image=image), self.base)

    def test_r6_preserves_existing_config_and_requires_both_confirmed_tables(self):
        tables = {"silver_checks_table": "silver.order_amount_checks", "silver_runs_table": "silver.silver_runs"}
        cm, _ = render(dict(self.config, **tables), self.base)
        actual = json.loads(cm['data']['config'])
        for key, value in dict(self.config, **tables).items():
            self.assertEqual(actual[key], value)
        for change in [{"silver_checks_table": "silver.order_amount_checks"},
                       dict(tables, silver_checks_table="other.order_amount_checks"),
                       dict(tables, silver_runs_table="silver.other")]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                render(dict(self.config, **change), self.base)

    def test_rejects_secret_or_node_pins_or_unconfirmed_model(self):
        for change in [{"hostname": "some-node"}, {"password": "not-a-secret"}, {"bedrock_model_id": "amazon.nova-lite-v1:0"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                render(dict(self.config, **change), self.base)

    def test_rejects_missing_workgroup_or_shared_workgroup(self):
        for change in [{"detect_workgroup": ""}, {"detect_workgroup": "primary"}, {"detect_workgroup": self.config["investigate_workgroup"]}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                render(dict(self.config, **change), self.base)

    def test_rejects_replacing_existing_agent_or_missing_probe_bundle(self):
        for change in [{"dagProcessor": {"dagBundleConfigList": []}}, {"extraEnv": "- name: AIRFLOW_AGENT_CONFIG\n  value: old"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                render(self.config, dict(self.base, **change))

    def test_rejects_plaintext_credentials_in_base_extra_env(self):
        with self.assertRaises(ValueError):
            render(self.config, dict(self.base, extraEnv="- name: ACCESS_TOKEN\n  value: test"))


if __name__ == "__main__":
    unittest.main()
