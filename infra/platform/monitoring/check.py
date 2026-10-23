"""Render and check safety boundaries without Docker or AWS credentials."""
import argparse
import json
import subprocess
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--prometheus-config", type=Path)
    args = parser.parse_args()
    chart = Path(__file__).resolve().parent / "chart"
    command = [args.helm, "template", "cq-monitoring", str(chart)]
    output = subprocess.run(command + ["-n", "monitoring"], capture_output=True, check=True)
    objects = [x for x in yaml.safe_load_all(output.stdout) if x]
    deployments = [x for x in objects if x["kind"] == "Deployment"]
    assert len(deployments) == 3
    assert not any(x["kind"] in {"Ingress", "Secret", "NodePool", "NodeClass", "DaemonSet"} for x in objects)
    cluster_kinds = {"NodePool", "StorageClass", "ClusterRole", "ClusterRoleBinding", "APIService"}
    for obj in objects:
        if obj["kind"] not in cluster_kinds:
            assert obj["metadata"]["namespace"] in {"monitoring", "kafka", "kube-system"}
        if obj["kind"] == "Service":
            assert obj["spec"]["type"] == "ClusterIP"
    cpu_m = memory_mi = 0
    for obj in deployments:
        spec = obj["spec"]["template"]["spec"]
        assert spec["nodeSelector"] == {"karpenter.sh/nodepool": "clothes-query-dev-api"}
        assert spec["tolerations"][0]["value"] == "api"
        assert obj["spec"]["strategy"]["type"] == "Recreate"
        for container in spec["containers"]:
            assert "@sha256:" in container["image"]
            assert not container.get("securityContext", {}).get("privileged", False)
            assert "--kubelet-insecure-tls" not in container.get("args", [])
            requests = container["resources"]["requests"]
            cpu_m += int(requests["cpu"].removesuffix("m"))
            memory_mi += int(requests["memory"].removesuffix("Mi"))
    assert (cpu_m, memory_mi) == (300, 896)
    configs = {x["metadata"]["name"]: x["data"] for x in objects if x["kind"] == "ConfigMap"}
    prom = yaml.safe_load(configs["monitoring-prometheus"]["prometheus.yml"])
    if args.prometheus_config:
        args.prometheus_config.parent.mkdir(parents=True, exist_ok=True)
        args.prometheus_config.write_text(configs["monitoring-prometheus"]["prometheus.yml"], encoding="utf-8")
    assert len(prom["scrape_configs"]) == 5
    assert len({x["job_name"] for x in prom["scrape_configs"]}) == 5
    rules = yaml.safe_load(configs["monitoring-prometheus"]["rules.yml"])
    assert len(rules["groups"][0]["rules"]) == 10
    dashboard = json.loads(configs["monitoring-grafana-dashboard"]["infrastructure.json"])
    assert len(dashboard["panels"]) == 10
    # Missing targets must show an alert instead of silently appearing healthy.
    assert sum("absent(" in r["expr"] for r in rules["groups"][0]["rules"]) == 5
    for bindings in [x for x in objects if x["kind"] in {"RoleBinding", "ClusterRoleBinding"}]:
        for subject in bindings["subjects"]:
            assert subject["namespace"] == "monitoring"
    rejected = subprocess.run(command, capture_output=True)
    assert rejected.returncode != 0  # default namespace must never work
    rejected = subprocess.run(command + ["-n", "monitoring", "--set", "grafana.image=grafana:latest"], capture_output=True)
    assert rejected.returncode != 0
    alternate = subprocess.run(command + ["-n", "monitoring", "-f", str(chart.parent / "new-node-values.yaml")], capture_output=True, check=True)
    alternate_objects = [x for x in yaml.safe_load_all(alternate.stdout) if x]
    pools = [x for x in alternate_objects if x["kind"] == "NodePool"]
    assert len(pools) == 1 and pools[0]["metadata"]["name"] == "clothes-query-dev-monitoring"
    print(f"PASS: {len(objects)} resources, existing WAS pool, 300m/896Mi, 5 jobs, 10 panels; namespace/image guards; optional new pool")


if __name__ == "__main__":
    main()
