"""Render Helm and validate against pinned Strimzi CRDs; never contacts a cluster."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]


def artifact(name, cache):
    pin = json.loads((ROOT / "artifacts.json").read_text())[name]
    path = cache / Path(pin["url"]).name
    if not path.exists():
        data = urllib.request.urlopen(pin["url"], timeout=30).read()
        assert hashlib.sha256(data).hexdigest() == pin["sha256"], name
        path.write_bytes(data)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"], name
    return path


def strict_schema(schema):
    # Kubernetes prunes unknown CR fields. Reject them here instead of silently losing settings.
    if isinstance(schema, dict):
        if (schema.get("type") == "object" and "properties" in schema
                and "additionalProperties" not in schema
                and not schema.get("x-kubernetes-preserve-unknown-fields")):
            schema["additionalProperties"] = False
        for value in list(schema.values()):
            strict_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            strict_schema(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helm", required=True, type=Path)
    args = parser.parse_args()
    helm = str(args.helm.resolve())
    cache = REPO / ".cache" / "kafka-verify"
    cache.mkdir(parents=True, exist_ok=True)
    crds = artifact("crds", cache)
    operator_chart = artifact("operatorChart", cache)
    schemas = {}
    for crd in yaml.safe_load_all(crds.read_text(encoding="utf-8")):
        if not crd:
            continue
        version = next(v for v in crd["spec"]["versions"] if v["name"] == "v1")
        schema = copy.deepcopy(version["schema"]["openAPIV3Schema"])
        strict_schema(schema)
        schema["properties"].update({"apiVersion": {"type": "string"},
                                     "kind": {"type": "string"}, "metadata": {"type": "object"}})
        schemas[crd["spec"]["names"]["kind"]] = schema

    def run(*arguments):
        return subprocess.run([helm, *map(str, arguments)], capture_output=True,
                              text=True, encoding="utf-8", check=False)

    with tempfile.TemporaryDirectory(prefix="cq-kafka-") as temp:
        def render(values=None, namespace="kafka", error=None):
            command = ["template", "cq-kafka", ROOT / "chart", "--namespace", namespace,
                       "--kube-version", "1.36.0"]
            if values is not None:
                path = Path(temp) / "values.yaml"
                path.write_text(yaml.safe_dump(values), encoding="utf-8")
                command += ["--values", path]
            result = run(*command)
            if error:
                assert result.returncode != 0 and error in result.stderr, result.stderr
                return []
            assert result.returncode == 0, result.stderr
            docs = [d for d in yaml.safe_load_all(result.stdout) if d]
            for doc in docs:
                assert doc["apiVersion"] == "kafka.strimzi.io/v1"
                jsonschema.Draft7Validator(schemas[doc["kind"]]).validate(doc)
            return docs

        lint = run("lint", ROOT / "chart", "--strict", "--namespace", "kafka")
        assert lint.returncode == 0, lint.stdout + lint.stderr
        assert render() == []
        base = {"kafka": {"enabled": True, "storageGi": 100, "retentionHours": 24},
                "topics": [{"name": "example-orders", "partitions": 3, "retentionMs": 86400000}],
                "clients": [{"name": "example-reader", "produceTopics": [],
                             "consumeTopics": ["example-orders"], "consumerGroups": ["example-reader"]}]}
        kafka_only = render(base)
        assert not any(d["kind"] == "KafkaConnect" for d in kafka_only)
        full = copy.deepcopy(base)
        full["connect"] = {"enabled": True, "image": "example.invalid/connect@sha256:" + "a" * 64,
                           "produceTopics": ["example-orders"]}
        docs = render(full)
        kafka = next(d["spec"]["kafka"] for d in docs if d["kind"] == "Kafka")
        listener = kafka["listeners"][0]
        assert listener["type"] == "internal" and listener["tls"]
        assert listener["authentication"]["type"] == "tls"
        assert kafka["authorization"]["type"] == "simple"
        assert not kafka["config"]["auto.create.topics.enable"]
        pool = next(d["spec"] for d in docs if d["kind"] == "KafkaNodePool")
        assert pool["replicas"] == 3 and set(pool["roles"]) == {"controller", "broker"}
        assert pool["storage"]["volumes"][0]["deleteClaim"] is False
        connect = next(d["spec"] for d in docs if d["kind"] == "KafkaConnect")
        assert connect["authentication"]["certificateAndKey"]["secretName"] == full.get("connect", {}).get("name", "clothes-query-dev-connect")
        assert connect["config"]["connector.client.config.override.policy"] == "None"
        assert connect["config"]["topic.creation.enable"] is False
        assert connect["config"]["config.providers.directory.param.allowed.paths"] == "/mnt/cdc-database"
        internal = [d for d in docs if d["kind"] == "KafkaTopic" and d["metadata"]["name"] != "example-orders"]
        assert len(internal) == 3 and all(d["spec"]["config"]["cleanup.policy"] == "compact" for d in internal)
        allowed_topics = {d["spec"]["topicName"] for d in docs if d["kind"] == "KafkaTopic"}
        for user in (d for d in docs if d["kind"] == "KafkaUser"):
            for acl in user["spec"]["authorization"]["acls"]:
                resource = acl["resource"]
                if resource["type"] != "cluster":
                    assert resource["patternType"] == "literal" and "*" not in resource["name"]
                if resource["type"] == "topic":
                    assert resource["name"] in allowed_topics
                assert not set(acl["operations"]) & {"All", "Delete", "Alter", "Create"}

        negatives = [
            ({"kafka": {"enabled": True}}, "kafka.storageGi is required"),
            ({"kafka": {"enabled": True, "storageGi": 100}}, "kafka.retentionHours is required"),
            ({"connect": {"enabled": True}}, "connect requires kafka.enabled"),
            ({"kafka": {"replicas": 1}}, "replicas"),
            ({"kafka": {"storageGi": -1}}, "storageGi"),
            ({"connect": {"image": "example.invalid/connect:latest"}}, "image"),
        ]
        for values, error in negatives:
            render(values, error=error)
        render(base, namespace="default", error="Install in namespace kafka")
        bad = copy.deepcopy(full); bad["connect"]["produceTopics"] = ["unknown"]
        render(bad, error="Connect ACL references an undefined")
        bad = copy.deepcopy(full); bad["connect"]["produceTopics"] = []
        render(bad, error="connect.produceTopics requires")
        bad = copy.deepcopy(base); bad["topics"] *= 2
        render(bad, error="/topics")
        bad = copy.deepcopy(base); bad["topics"][0]["name"] = "*"
        render(bad, error="name")
        bad = copy.deepcopy(base); bad["clients"][0]["consumerGroups"] = []
        render(bad, error="Consumers require explicit")

        op = run("template", "strimzi", operator_chart, "--namespace", "kafka",
                 "--values", ROOT / "operator-values.yaml", "--include-crds", "--kube-version", "1.36.0")
        assert op.returncode == 0, op.stderr
        deployment = next(d for d in yaml.safe_load_all(op.stdout) if d and d["kind"] == "Deployment")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "@sha256:" in container["image"]
        env = {e["name"]: e for e in container["env"]}
        assert env["STRIMZI_NAMESPACE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"
        # Official chart omits this env when using the operator's true default.
        assert env.get("STRIMZI_NETWORK_POLICY_GENERATION", {"value": "true"})["value"] == "true"
        assert yaml.safe_load((ROOT / "operator-values.yaml").read_text())["generateNetworkPolicy"] is True
        storage = yaml.safe_load((ROOT / "storage-class.yaml").read_text())
        assert storage["provisioner"] == "ebs.csi.eks.amazonaws.com"
        assert storage["reclaimPolicy"] == "Retain" and storage["parameters"]["encrypted"] == "true"
        assert storage["volumeBindingMode"] == "WaitForFirstConsumer"
    print(f"PASS: lint, disabled/Kafka/Connect rendering, {len(docs)} CRs against Strimzi 1.3.0 schemas, 12 rejected inputs, operator/storage checks")
    print("No Kubernetes/AWS connection, apply, push or runtime claim.")


if __name__ == "__main__":
    main()
