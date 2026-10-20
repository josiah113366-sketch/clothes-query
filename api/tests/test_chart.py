"""Helm chart 렌더 검사. Helm이 없으면 건너뛴다(`python infra/checks/install_helm.py`로 받는다)."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "api" / "deploy" / "chart"
DIGEST = (
    "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/was@sha256:" + "a" * 64
)


def _helm() -> str:
    path = os.environ.get("HELM") or str(REPO / ".cache" / "helm" / "linux-amd64" / "helm")
    if not Path(path).exists():
        pytest.skip("Helm 없음")
    return path


def _render(*sets: str) -> subprocess.CompletedProcess:
    args = [_helm(), "template", "api", str(CHART), "-n", "api"]
    for item in sets:
        args += ["--set", item]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_renders_internal_http_alb_and_secure_pod():
    result = _render(f"image={DIGEST}", "ingress.inboundCIDRs={10.70.0.0/16}")
    assert result.returncode == 0, result.stderr
    docs = {d["kind"]: d for d in yaml.safe_load_all(result.stdout) if d}
    params = docs["IngressClassParams"]["spec"]
    assert params["scheme"] == "internal" and params["inboundCIDRs"] == ["10.70.0.0/16"]
    assert params["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "api"
    assert docs["IngressClass"]["spec"]["controller"] == "eks.amazonaws.com/alb"
    ingress = docs["Ingress"]["metadata"]["annotations"]
    assert ingress["alb.ingress.kubernetes.io/listen-ports"] == '[{"HTTP": 80}]'
    assert ingress["alb.ingress.kubernetes.io/healthcheck-path"] == "/readyz"
    pod = docs["Deployment"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert docs["Deployment"]["spec"]["replicas"] == 1
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    env = {e["name"]: e for e in container["env"]}
    assert env["PGSSLMODE"]["value"] == "verify-full"
    assert env["PGPASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "api-database"
    assert env["KAFKA_SECURITY_PROTOCOL"]["value"] == "SSL"
    assert "DATABASE_URL" not in env
    assert docs["Service"]["spec"]["type"] == "ClusterIP"
    # 전용 노드 풀: 기존 Kafka 풀과 다른 이름, taint, t3a.medium 한 대 상한
    pool = docs["NodePool"]["spec"]
    assert docs["NodePool"]["metadata"]["name"] == "clothes-query-dev-api"
    assert pool["template"]["spec"]["nodeClassRef"]["name"] == "clothes-query-dev-compute"
    assert pool["template"]["spec"]["taints"] == [
        {"key": "clothes-query/dedicated", "value": "api", "effect": "NoSchedule"}
    ]
    types = next(r for r in pool["template"]["spec"]["requirements"]
                 if r["key"] == "node.kubernetes.io/instance-type")  # fmt: skip
    assert types["values"] == ["t3a.medium"] and pool["limits"]["cpu"] == "2"
    terms = pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert terms["nodeSelectorTerms"][0]["matchExpressions"][0]["values"] == [
        "clothes-query-dev-api"
    ]
    assert pod["tolerations"][0]["key"] == "clothes-query/dedicated"


@pytest.mark.parametrize(
    ("sets", "message"),
    [
        (("image=was:latest", "ingress.inboundCIDRs={10.0.0.0/16}"), "image must be"),
        ((f"image={DIGEST}",), "inboundCIDRs is required"),
        ((f"image={DIGEST}", "ingress.inboundCIDRs={0.0.0.0/0}"), "not 0.0.0.0/0"),
        ((f"image={DIGEST}", "ingress.inboundCIDRs={10.0.0.0/16}", "replicas=0"), "replicas"),
        (
            (
                f"image={DIGEST}",
                "ingress.inboundCIDRs={10.0.0.0/16}",
                "nodePool.name=clothes-query-dev-compute",
            ),
            "shared Kafka pool",
        ),
    ],
)
def test_rejects_bad_values(sets, message):
    result = _render(*sets)
    assert result.returncode != 0 and message in result.stderr
