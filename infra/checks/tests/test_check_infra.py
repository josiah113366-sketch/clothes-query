from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from infra.checks import check_infra as checks


class CheckRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="infra-checks-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.infra = self.root / "infra"
        self.test_root = self.infra / "tests"
        self.test_root.mkdir(parents=True)
        module = self.infra / "modules" / "example"
        module.mkdir(parents=True)
        (module / "main.tf").write_text('resource "aws_s3_bucket" "example" {}\n')

    def suite(self, text: str) -> None:
        (self.test_root / "example.tftest.hcl").write_text(text, encoding="utf-8")

    def test_plan_with_mocked_module_is_accepted(self) -> None:
        self.suite('''
mock_provider "aws" {}
run "example" {
  command = plan
  module { source = "../modules/example" }
}
''')
        suites, count = checks.mock_suites(self.test_root, self.infra)
        self.assertEqual((len(suites), count), (1, 1))

    def test_implicit_apply_and_explicit_apply_are_rejected(self) -> None:
        for command in ("", "command = apply"):
            with self.subTest(command=command):
                self.suite('mock_provider "aws" {}\nrun "x" { ' + command +
                           ' module { source = "../modules/example" } }')
                with self.assertRaisesRegex(checks.CheckError, "explicit command = plan"):
                    checks.mock_suites(self.test_root, self.infra)

    def test_missing_mock_is_rejected(self) -> None:
        self.suite('run "x" { command = plan module { source = "../modules/example" } }')
        with self.assertRaisesRegex(checks.CheckError, "Missing mock providers.*aws"):
            checks.mock_suites(self.test_root, self.infra)

    def test_nested_child_provider_also_needs_mock(self) -> None:
        child = self.infra / "modules" / "child"
        child.mkdir()
        (child / "main.tf").write_text('resource "kubernetes_namespace_v1" "test" {}')
        with (self.infra / "modules" / "example" / "main.tf").open("a") as stream:
            stream.write('\nmodule "child" { source = "../child" }')
        self.suite('''
mock_provider "aws" {}
run "x" { command = plan module { source = "../modules/example" } }
''')
        with self.assertRaisesRegex(checks.CheckError, "Missing mock providers.*kubernetes"):
            checks.mock_suites(self.test_root, self.infra)

    def test_real_provider_configuration_is_rejected(self) -> None:
        self.suite('''
provider "aws" { region = "ap-northeast-1" }
mock_provider "aws" {}
run "x" { command = plan module { source = "../modules/example" } }
''')
        with self.assertRaisesRegex(checks.CheckError, "Real test provider"):
            checks.mock_suites(self.test_root, self.infra)

    def test_provider_alias_requires_corresponding_mock(self) -> None:
        (self.infra / "modules" / "example" / "main.tf").write_text(
            'resource "aws_s3_bucket" "test" { provider = aws.other }'
        )
        self.suite('''
mock_provider "aws" {}
run "x" { command = plan module { source = "../modules/example" } }
''')
        with self.assertRaisesRegex(checks.CheckError, r"Missing mock providers.*aws.other"):
            checks.mock_suites(self.test_root, self.infra)

    def test_remote_or_outside_modules_are_rejected(self) -> None:
        for source in ("example/module/aws", "../../../outside"):
            with self.subTest(source=source):
                self.suite('mock_provider "aws" {}\nrun "x" { command = plan module { source = "' +
                           source + '" } }')
                with self.assertRaises(checks.CheckError):
                    checks.mock_suites(self.test_root, self.infra)

    def test_child_environment_drops_ambient_auth_and_cli_arguments(self) -> None:
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "test-only",
            "AWS_PROFILE": "test-only",
            "TF_CLI_ARGS_init": "-migrate-state",
            "TF_VAR_password": "test-only",
            "KUBE_CONFIG_PATH": "test-only",
        }):
            environment = checks.child_environment(self.root)
        for key in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "TF_CLI_ARGS_init",
                    "TF_VAR_password", "KUBE_CONFIG_PATH"):
            self.assertNotIn(key, environment)
        self.assertEqual(Path(environment["AWS_CONFIG_FILE"]).read_text(), "")
        self.assertEqual(environment["AWS_EC2_METADATA_DISABLED"], "true")

    def test_snapshot_uses_tracked_edits_without_copying_state_or_local_inputs(self) -> None:
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        bootstrap = repo / "infra" / "bootstrap"
        bootstrap.mkdir(parents=True)
        (bootstrap / "main.tf").write_text("# original")
        (bootstrap / ".terraform.lock.hcl").write_text("# lock")
        (bootstrap / "deployment.auto.tfvars.json").write_text('{"enabled": true}')
        (bootstrap / "deployment.backend.hcl").write_text('bucket = "test-state"')
        (bootstrap / "deployment.local.tfvars.json").write_text('{"personal": "local-only"}')
        subprocess.run(["git", "-C", str(repo), "add", "infra"], check=True)
        (bootstrap / "main.tf").write_text("# tracked working edit")
        (bootstrap / "terraform.tfstate").write_text("local state")
        (bootstrap / "deployment.local.tfvars").write_text("local input")
        (bootstrap / ".terraform").mkdir()
        (bootstrap / ".terraform" / "terraform.tfstate").write_text("backend metadata")
        destination = self.root / "snapshot"
        destination.mkdir()
        checks.snapshot(repo, destination, None)
        copied = destination / "infra" / "bootstrap"
        self.assertEqual((copied / "main.tf").read_text(), "# tracked working edit")
        self.assertTrue((copied / ".terraform.lock.hcl").is_file())
        self.assertEqual((copied / "deployment.auto.tfvars.json").read_text(), '{"enabled": true}')
        self.assertFalse((copied / "deployment.local.tfvars.json").exists())
        self.assertFalse((copied / "deployment.backend.hcl").exists())
        self.assertEqual(len(list(copied.iterdir())), 3)
        self.assertEqual((bootstrap / "terraform.tfstate").read_text(), "local state")
        self.assertEqual((bootstrap / ".terraform" / "terraform.tfstate").read_text(),
                         "backend metadata")


if __name__ == "__main__":
    unittest.main()
