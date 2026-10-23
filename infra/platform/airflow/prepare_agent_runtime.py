"""Render opt-in agent ConfigMap and Helm overlay. No AWS/Kubernetes calls."""
import argparse
import copy
import json
from pathlib import Path
import re

import yaml

ACCOUNT = "827913617635"
REGION = "ap-northeast-1"
MODEL = "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
CONFIG_KEYS = {"detect_image", "investigate_image", "detect_workgroup", "investigate_workgroup",
               "region", "bedrock_model_id", "investigate_max"}
REQUIRED = CONFIG_KEYS - {"investigate_max"}
CM_NAME = "airflow-agent-runtime"
ENV_NAME = "AIRFLOW_AGENT_CONFIG"
BUNDLE_NAME = "agent-dags"


def render(config, base):
    if not isinstance(base, dict):
        raise ValueError("Base values must be a YAML mapping")
    if not isinstance(config, dict) or REQUIRED - config.keys() or config.keys() - CONFIG_KEYS:
        raise ValueError("Supply only documented agent settings; all six required keys must be present")
    config = copy.deepcopy(config)
    if config["region"] != REGION or config["bedrock_model_id"] != MODEL:
        raise ValueError("Use the confirmed Tokyo region and JP Haiku profile")
    for key, repo in [("detect_image", "detection-job"), ("investigate_image", "investigation-agent")]:
        pattern = rf"{ACCOUNT}\.dkr\.ecr\.{REGION}\.amazonaws\.com/clothes-query-dev/{repo}@sha256:[0-9a-f]{{64}}"
        if not isinstance(config[key], str) or not re.fullmatch(pattern, config[key]):
            raise ValueError(f"{key} must use the expected account/region/repository and immutable sha256 digest")
    for key in ("detect_workgroup", "investigate_workgroup"):
        if not isinstance(config[key], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", config[key]) or config[key] == "primary":
            raise ValueError("Supply dedicated Athena workgroups")
    if config["detect_workgroup"] == config["investigate_workgroup"]:
        raise ValueError("Detection and investigation workgroups must be separate")
    count = config.get("investigate_max", 3)
    if type(count) is not int or not 1 <= count <= 3:
        raise ValueError("Initial investigation batch size must be between one and three")
    config["investigate_max"] = count
    bundles = copy.deepcopy(base.get("dagProcessor", {}).get("dagBundleConfigList", []))
    if not bundles or any(b.get("name") == BUNDLE_NAME for b in bundles):
        raise ValueError("Base values must contain the existing Git bundle, without agent-dags already added")
    if not any(b.get("name") == "dags-folder" and b.get("kwargs", {}).get("subdir") == "infra/platform/airflow/dags" for b in bundles):
        raise ValueError("Preserve the existing infrastructure DAG bundle")
    env = yaml.safe_load(base.get("extraEnv") or "[]")
    if not isinstance(env, list) or any(not isinstance(e, dict) or not e.get("name") for e in env):
        raise ValueError("Base extraEnv must be a YAML environment list")
    if any(e["name"] == ENV_NAME for e in env):
        raise ValueError("Agent configuration environment is already supplied; review it before replacement")
    if any("value" in e and re.search(r"PASSWORD|SECRET|TOKEN|CREDENTIAL|ACCESS_KEY", e["name"], re.I) for e in env):
        raise ValueError("Use Secret references instead of plaintext credentials in extraEnv")
    env = copy.deepcopy(env)
    env.append({"name": ENV_NAME, "valueFrom": {"configMapKeyRef": {"name": CM_NAME, "key": "config"}}})
    bundles.append({"name": BUNDLE_NAME, "classpath": "airflow.providers.git.bundles.git.GitDagBundle",
                    "kwargs": {"repo_url": "https://github.com/josiah113366-sketch/clothes-query.git",
                               "tracking_ref": "main", "subdir": "agent/dags", "refresh_interval": 60}})
    cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": CM_NAME, "namespace": "airflow"},
          "data": {"config": json.dumps(config, ensure_ascii=False, sort_keys=True)}}
    overlay = {"extraEnv": yaml.safe_dump(env, sort_keys=False), "dagProcessor": {"dagBundleConfigList": bundles},
               "config": {"core": {"dags_are_paused_at_creation": "True"}}}
    return cm, overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--base-values", type=Path, required=True, help="Reviewed effective base values, including existing extraEnv and bundles")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        cm, values = render(json.loads(args.config.read_text(encoding="utf-8-sig")),
                            yaml.safe_load(args.base_values.read_text(encoding="utf-8-sig")))
        targets = [args.output_dir / "agent-configmap.json", args.output_dir / "agent-values.json"]
        if any(p.exists() for p in targets):
            raise ValueError("Output files already exist; choose a new output directory for review")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for target, data in zip(targets, (cm, values)):
            target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError):
        parser.exit(1, "Preparation failed: check the input shape, confirmed settings, immutable digests, base values and output paths. Input values are not printed.\n")
    print("Prepared ConfigMap and Helm overlay only; no resources applied and no DAGs triggered")


if __name__ == "__main__":
    main()
