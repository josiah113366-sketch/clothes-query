"""Verify pinned upstream chart and the shared-WAS installation boundaries."""
import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

import yaml


def chart_archive():
    folder = Path(__file__).resolve().parent
    root = folder.parents[2]
    lock = json.loads((folder / "chart.lock.json").read_text())
    archive = root / ".cache" / f"argo-cd-{lock['version']}.tgz"
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        data = urllib.request.urlopen(lock["url"], timeout=60).read()
        if hashlib.sha256(data).hexdigest() != lock["sha256"]:
            raise ValueError("Upstream chart checksum mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["sha256"]:
        raise ValueError("Cached chart checksum mismatch")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    archive = chart_archive()
    proc = subprocess.run(
        [args.helm, "template", "argocd", str(archive), "--namespace", "argocd",
         "--kube-version", "1.36.0", "-f", str(folder / "development-values.yaml")],
        capture_output=True, check=True,
    )
    objects = [x for x in yaml.safe_load_all(proc.stdout) if x]
    active = [x for x in objects if x["kind"] in {"Deployment", "StatefulSet"} and x["spec"].get("replicas", 1)]
    assert len(active) == 4
    assert not any(x["kind"] in {"Application", "ApplicationSet", "NodePool", "NodeClass", "Ingress", "PersistentVolumeClaim", "Job"} for x in objects)
    cpu_m = memory_mi = 0
    for obj in active:
        spec = obj["spec"]["template"]["spec"]
        assert spec["nodeSelector"]["karpenter.sh/nodepool"] == "clothes-query-dev-api"
        assert any(t.get("key") == "clothes-query/dedicated" and t.get("value") == "api" for t in spec["tolerations"])
        for c in spec["containers"]:
            assert "@sha256:" in c["image"]
            r = c["resources"]["requests"]
            cpu_m += int(r["cpu"].removesuffix("m"))
            memory_mi += int(r["memory"].removesuffix("Mi"))
    assert (cpu_m, memory_mi) == (275, 704)
    for obj in objects:
        if obj["kind"] == "Service":
            assert obj["spec"].get("type", "ClusterIP") == "ClusterIP"
        if obj["kind"] == "ClusterRole":
            for rule in obj["rules"]:
                assert set(rule.get("verbs", [])) <= {"get", "list", "watch"}
                assert "*" not in rule.get("resources", [])
                assert "secrets" not in rule.get("resources", [])
    permissions = list(yaml.safe_load_all((folder / "was-access.yaml").read_text()))
    for obj in permissions:
        assert obj["metadata"]["namespace"] == "api"
        for rule in obj.get("rules", []):
            assert not set(rule["resources"]) & {"secrets", "serviceaccounts", "roles", "rolebindings", "pods/exec", "*"}
    projects = list(yaml.safe_load_all((folder / "projects.yaml").read_text()))
    assert len(projects) == 2 and all(x["kind"] == "AppProject" for x in projects)
    assert all(not p["spec"]["clusterResourceWhitelist"] for p in projects)
    assert projects[0]["spec"]["destinations"] == []
    assert projects[1]["spec"]["destinations"] == [{"namespace": "api", "server": "https://kubernetes.default.svc"}]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(proc.stdout)
    print(f"PASS: chart checksum, {len(objects)} objects, 4 active Pods, 275m/704Mi, WAS-only app scope, no Application or new infrastructure")


if __name__ == "__main__":
    main()
