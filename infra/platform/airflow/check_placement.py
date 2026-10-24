"""Reject rendered Airflow workloads tied to a single node. No cluster access."""
import argparse
from pathlib import Path

import yaml

POOL_KEY = "karpenter.sh/nodepool"
POOL = "clothes-query-dev-compute"
HOST_KEY = "kubernetes.io/hostname"


def check(objects):
    checked = 0
    deployments = set()
    for obj in objects:
        if not obj or obj.get("kind") not in {"Deployment", "StatefulSet", "Job", "Pod"}:
            continue
        spec = obj["spec"] if obj["kind"] == "Pod" else obj["spec"]["template"]["spec"]
        selector = spec.get("nodeSelector") or {}
        if selector.get(POOL_KEY) != POOL:
            raise ValueError("Airflow workload must select the shared compute node pool")
        if HOST_KEY in selector or spec.get("nodeName"):
            raise ValueError("Airflow workload must not select an individual node")
        required = (spec.get("affinity") or {}).get("nodeAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution", {})
        for term in required.get("nodeSelectorTerms", []):
            if any(e.get("key") == HOST_KEY for e in term.get("matchExpressions", [])) or term.get("matchFields"):
                raise ValueError("Airflow required node affinity must not pin an individual node")
        if obj["kind"] == "Deployment":
            deployments.add(obj["metadata"]["name"])
        checked += 1
    if not {"airflow-api-server", "airflow-scheduler", "airflow-dag-processor"} <= deployments:
        raise ValueError("Render the complete airflow release before checking placement")
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        count = check(yaml.safe_load_all(args.manifest.read_text(encoding="utf-8-sig")))
    except (ValueError, KeyError) as error:
        parser.exit(1, f"Placement check failed: {error}\n")
    print(f"PASS: {count} Airflow workloads select the compute pool without individual node pins")


if __name__ == "__main__":
    main()
