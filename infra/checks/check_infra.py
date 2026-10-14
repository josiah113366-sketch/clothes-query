"""Check tracked Terraform in an isolated copy without deployment credentials."""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

import hcl2


class CheckError(Exception):
    """A failed check or an unsupported test configuration."""


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise CheckError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def snapshot(repo: Path, destination: Path, ref: str | None) -> None:
    """Use current tracked file contents, or a committed ref; never copy local state."""
    if ref:
        content = git(repo, "archive", "--format=zip", ref, "--", "infra")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = [(item.filename, archive.read(item)) for item in archive.infolist()
                       if not item.is_dir()]
    else:
        paths = git(repo, "ls-files", "-z", "--", "infra").split(b"\0")
        entries = []
        for raw in filter(None, paths):
            name = raw.decode("utf-8")
            source = repo / name
            if source.is_symlink():
                raise CheckError(f"Tracked symlinks are not supported: {name}")
            entries.append((name, source.read_bytes()))
    for name, content in entries:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "infra":
            raise CheckError(f"Invalid snapshot path: {name}")
        if (".terraform" in relative.parts or ".tfstate" in relative.name
                or relative.name.endswith((".tfplan", ".backend.hcl"))
                or relative.name.startswith("deployment.local.")):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def terraform_roots(infra: Path) -> list[Path]:
    candidates = [infra / "bootstrap"]
    stacks = infra / "stacks"
    if stacks.is_dir():
        candidates.extend(sorted(path for path in stacks.iterdir() if path.is_dir()))
    candidates.append(infra / "tests")
    return [path for path in candidates if path.is_dir() and any(path.glob("*.tf"))]


def load_hcl(path: Path) -> dict:
    options = hcl2.utils.SerializationOptions(
        strip_string_quotes=True, with_comments=False, explicit_blocks=False
    )
    try:
        return hcl2.loads(path.read_text(encoding="utf-8-sig"), serialization_options=options)
    except Exception as error:
        raise CheckError(f"Cannot parse {path.name}: {type(error).__name__}") from error


def reference(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return value[2:-1]
    return value


def module_providers(module: Path, infra: Path, visited: set[Path]) -> set[str]:
    module = module.resolve()
    if not module.is_relative_to(infra.resolve()) or not module.is_dir():
        raise CheckError("Mock test modules must be local directories inside infra/.")
    if module in visited:
        return set()
    visited.add(module)
    providers: set[str] = set()
    for path in sorted(module.glob("*.tf")):
        document = load_hcl(path)
        if document.get("provider"):
            raise CheckError(f"Real provider configuration in mock test module: {path.name}")
        for kind in ("resource", "data", "ephemeral"):
            for block in document.get(kind, []):
                for resource_type, instances in block.items():
                    for body in instances.values():
                        if resource_type.startswith("terraform_"):
                            raise CheckError("Built-in data/state access is not allowed in mock tests.")
                        provider = reference(body.get("provider", resource_type.split("_")[0]))
                        if provider.split(".")[0] not in {"aws", "kubernetes"}:
                            raise CheckError(f"Unsupported mock provider: {provider}")
                        providers.add(provider)
        for block in document.get("module", []):
            for body in block.values():
                source = body.get("source", "")
                if not source.startswith(("./", "../")) or body.get("providers"):
                    raise CheckError("Mock test child modules need local sources without provider remapping.")
                providers.update(module_providers(module / source, infra, visited))
    return providers


def mock_suites(test_root: Path, infra: Path) -> tuple[list[Path], int]:
    """Require explicit plan runs and mocks for every used AWS/Kubernetes provider."""
    suites = sorted(test_root.glob("*.tftest.hcl"))
    count = 0
    for suite in suites:
        document = load_hcl(suite)
        if document.get("provider"):
            raise CheckError(f"Real test provider configuration is not allowed: {suite.name}")
        mocks: set[str] = set()
        for block in document.get("mock_provider", []):
            for name, body in block.items():
                mocks.add(name + ("." + body["alias"] if body.get("alias") else ""))
        runs = document.get("run", [])
        if not runs:
            raise CheckError(f"No run blocks in mock suite: {suite.name}")
        for block in runs:
            for name, body in block.items():
                if body.get("command") != "plan":
                    raise CheckError(f"Only explicit command = plan is allowed: {suite.name}/{name}")
                if body.get("providers"):
                    raise CheckError(f"Test provider remapping is not supported: {suite.name}/{name}")
                selected = body.get("module", [])
                if selected:
                    if len(selected) != 1:
                        raise CheckError("Each mock run must select exactly one module.")
                    source = selected[0].get("source", "")
                    if not source.startswith(("./", "../")):
                        raise CheckError("Mock runs must use local modules.")
                    module = test_root / source
                else:
                    module = test_root
                required = module_providers(module, infra, set())
                missing = required - mocks
                if missing:
                    raise CheckError(f"Missing mock providers in {suite.name}/{name}: {', '.join(sorted(missing))}")
                count += 1
    return suites, count


def child_environment(scratch: Path) -> dict[str, str]:
    # Remove inherited CLI arguments, backend settings and cloud auth for child tools.
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("AWS_", "TF_", "KUBE"))
    }
    empty = scratch / "empty-config"
    empty.write_text("", encoding="utf-8")
    cli_config = scratch / "terraform.rc"
    cli_config.write_text("disable_checkpoint = true\n", encoding="utf-8")
    cache = scratch / "provider-cache"
    cache.mkdir()
    environment.update({
        "AWS_SHARED_CREDENTIALS_FILE": str(empty),
        "AWS_CONFIG_FILE": str(empty),
        "AWS_EC2_METADATA_DISABLED": "true",
        "KUBECONFIG": str(empty),
        "TF_CLI_CONFIG_FILE": str(cli_config),
        "TF_PLUGIN_CACHE_DIR": str(cache),
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
        "CHECKPOINT_DISABLE": "1",
    })
    return environment


def execute(binary: str, scratch: Path, env: dict[str, str], *args: str) -> None:
    print("terraform " + " ".join(args), flush=True)
    result = subprocess.run([binary, *args], cwd=scratch, env=env, check=False)
    if result.returncode:
        raise CheckError(f"Terraform check failed (exit {result.returncode}).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Check committed infra at this Git ref instead of current tracked files.")
    parser.add_argument("--terraform", default="terraform", help="Terraform executable path or command name.")
    arguments = parser.parse_args()
    binary = shutil.which(arguments.terraform)
    if not binary:
        print("Terraform executable not found. Install Terraform or pass --terraform PATH.", file=sys.stderr)
        return 1
    binary = str(Path(binary).resolve())
    repo = Path(__file__).resolve().parents[2]
    try:
        with tempfile.TemporaryDirectory(prefix="clothes-query-infra-") as folder:
            scratch = Path(folder)
            snapshot(repo, scratch, arguments.ref)
            infra = scratch / "infra"
            roots = terraform_roots(infra)
            if not roots:
                raise CheckError("No Terraform roots found under bootstrap/, stacks/* or tests/.")
            for root in roots:
                if not (root / ".terraform.lock.hcl").is_file():
                    raise CheckError(f"Commit a provider lockfile first: {root.relative_to(scratch)}")
            test_root = infra / "tests"
            suites, runs = mock_suites(test_root, infra)
            env = child_environment(scratch)
            execute(binary, scratch, env, "fmt", "-check", "-recursive", "infra")
            for root in roots:
                chdir = "-chdir=" + root.relative_to(scratch).as_posix()
                execute(binary, scratch, env, chdir, "init", "-backend=false", "-input=false",
                        "-lockfile=readonly", "-no-color")
                execute(binary, scratch, env, chdir, "validate", "-no-color")
            if suites:
                filters = ["-filter=" + suite.name for suite in suites]
                execute(binary, scratch, env, "-chdir=infra/tests", "test", "-no-color", *filters)
            print(f"PASS: {len(roots)} Terraform roots; {len(suites)} mock suites / {runs} plan runs.")
            return 0
    except (CheckError, OSError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
