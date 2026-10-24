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
    parser.add_argument("--alertmanager-config", type=Path)
    args = parser.parse_args()
    chart = Path(__file__).resolve().parent / "chart"
    command = [args.helm, "template", "cq-monitoring", str(chart)]
    output = subprocess.run(command + ["-n", "monitoring"], capture_output=True, check=True)
    objects = [x for x in yaml.safe_load_all(output.stdout) if x]
    deployments = [x for x in objects if x["kind"] == "Deployment"]
    assert len(deployments) == 4
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
    assert (cpu_m, memory_mi) == (325, 960)
    configs = {x["metadata"]["name"]: x["data"] for x in objects if x["kind"] == "ConfigMap"}
    grafana = next(x for x in deployments if x["metadata"]["name"] == "monitoring-grafana")
    grafana_env = grafana["spec"]["template"]["spec"]["containers"][0]["env"]
    assert {x["name"]: x.get("value") for x in grafana_env}["GF_PLUGINS_PREINSTALL_AUTO_UPDATE"] == "false"
    prom = yaml.safe_load(configs["monitoring-prometheus"]["prometheus.yml"])
    if args.prometheus_config:
        args.prometheus_config.parent.mkdir(parents=True, exist_ok=True)
        args.prometheus_config.write_text(configs["monitoring-prometheus"]["prometheus.yml"], encoding="utf-8")
    assert len(prom["scrape_configs"]) == 7
    assert len({x["job_name"] for x in prom["scrape_configs"]}) == 7
    rules = yaml.safe_load(configs["monitoring-prometheus"]["rules.yml"])
    assert len(rules["groups"][0]["rules"]) == 10
    dashboard = json.loads(configs["monitoring-grafana-dashboard"]["infrastructure.json"])
    assert len(dashboard["panels"]) == 17
    node_jobs = {j['job_name']: j for j in prom['scrape_configs'] if j['job_name'].startswith('clothes-query-node-')}
    usage = node_jobs['clothes-query-node-usage']
    assert usage['metrics_path'] == '/metrics/resource' and usage['scheme'] == 'https'
    assert usage['tls_config'] == {'ca_file': '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'}
    assert usage['metric_relabel_configs'][0]['action'] == 'keep'
    state_role = next(o for o in objects if o['kind'] == 'ClusterRole' and o['metadata']['name'] == 'clothes-query-monitoring-node-state')
    assert state_role['rules'] == [{'apiGroups': [''], 'resources': ['nodes', 'pods'], 'verbs': ['list', 'watch']}]
    kubelet_role = next(o for o in objects if o['kind'] == 'ClusterRole' and o['metadata']['name'] == 'clothes-query-monitoring-kubelet-read')
    assert kubelet_role['rules'] == [
        {'apiGroups': [''], 'resources': ['nodes'], 'verbs': ['get', 'list', 'watch']},
        {'apiGroups': [''], 'resources': ['nodes/metrics'], 'verbs': ['get']}]
    disabled = subprocess.run(command + ['-n', 'monitoring', '--set', 'nodeMetrics.enabled=false'], capture_output=True, check=True)
    disabled_objects = [o for o in yaml.safe_load_all(disabled.stdout) if o]
    assert len([o for o in disabled_objects if o['kind'] == 'Deployment']) == 3
    assert not any(o['metadata']['name'] == 'monitoring-node-state' for o in disabled_objects)
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
    alert_flags = ["-n", "monitoring", "--set", "alertmanager.enabled=true"]
    assert subprocess.run(command + alert_flags, capture_output=True).returncode != 0
    alert_flags += ["--set", "alertmanager.topicArn=arn:aws:sns:ap-northeast-1:000000000000:clothes-query-dev-infra-alerts"]
    enabled = subprocess.run(command + alert_flags, capture_output=True, check=True)
    enabled_objects = [x for x in yaml.safe_load_all(enabled.stdout) if x]
    enabled_configs = {x["metadata"]["name"]: x["data"] for x in enabled_objects if x["kind"] == "ConfigMap"}
    if args.alertmanager_config:
        args.alertmanager_config.parent.mkdir(parents=True, exist_ok=True)
        args.alertmanager_config.write_text(enabled_configs["monitoring-alertmanager"]["alertmanager.yml"], encoding="utf-8")
    enabled_prom = yaml.safe_load(enabled_configs["monitoring-prometheus"]["prometheus.yml"])
    assert enabled_prom["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == ["monitoring-alertmanager:9093"]
    assert len(enabled_objects) == len(objects) + 4
    delivery = next(x for x in enabled_objects if x["kind"] == "Deployment" and x["metadata"]["name"] == "monitoring-alertmanager")
    assert delivery["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    assert delivery["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"] == {"cpu": "25m", "memory": "64Mi"}
    assert not any(x["kind"] in {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "PersistentVolumeClaim"} for x in enabled_objects if x["metadata"]["name"] == "monitoring-alertmanager")
    print(f"PASS: {len(objects)} resources, existing WAS pool, 325m/960Mi, 7 jobs, 17 panels; namespace/image guards; optional new pool")


if __name__ == "__main__":
    main()
