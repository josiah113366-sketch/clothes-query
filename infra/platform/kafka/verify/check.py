"""Render Helm and validate against pinned Strimzi CRDs; never contacts a cluster."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
import subprocess
import tempfile
import urllib.request

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
# Kafka UI (ui.enabled) renders plain Kubernetes objects next to the Strimzi CRs.
UI_KINDS = {"Deployment": "apps/v1", "Service": "v1", "NetworkPolicy": "networking.k8s.io/v1"}
BUSINESS_TOPICS = {"clickstream", "members-events", "orders", "order-items", "payments"}


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
                if doc["kind"] == "ConfigMap":
                    assert doc["apiVersion"] == "v1" and set(doc["data"]) == {"kafka.yml", "connect.yml"}
                    for config in doc["data"].values():
                        assert yaml.safe_load(config)["rules"]
                    continue
                if doc["kind"] in UI_KINDS:
                    assert doc["apiVersion"] == UI_KINDS[doc["kind"]]
                    continue
                assert doc["apiVersion"] == "kafka.strimzi.io/v1"
                jsonschema.Draft7Validator(schemas[doc["kind"]]).validate(doc)
            return docs

        lint = run("lint", ROOT / "chart", "--strict", "--namespace", "kafka")
        assert lint.returncode == 0, lint.stdout + lint.stderr
        assert render() == []
        retention_defaults = render({"kafka": {"enabled": True}})
        default_broker = next(d["spec"]["kafka"] for d in retention_defaults if d["kind"] == "Kafka")
        assert default_broker["config"]["log.retention.hours"] == 24
        default_pool = next(d["spec"] for d in retention_defaults if d["kind"] == "KafkaNodePool")
        assert default_pool["replicas"] == 3
        assert default_pool["storage"]["volumes"][0]["size"] == "20Gi"
        assert default_pool["storage"]["volumes"][0]["deleteClaim"] is False
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
        assert not any(d["kind"] == "ConfigMap" for d in docs)
        assert all("metricsConfig" not in d["spec"] for d in docs if d["kind"] == "KafkaConnect")
        compact = copy.deepcopy(full)
        compact_profile = yaml.safe_load((ROOT / "single-node-values.yaml").read_text(encoding="utf-8"))
        compact.update(copy.deepcopy(compact_profile))
        compact["kafka"]["enabled"] = True
        compact["topics"][0]["retentionMs"] = 259200000
        compact["connect"].update(enabled=True, image=full["connect"]["image"], produceTopics=["example-orders"])
        compact_docs = render(compact)
        compact_pool = next(d["spec"] for d in compact_docs if d["kind"] == "KafkaNodePool")
        compact_kafka = next(d["spec"] for d in compact_docs if d["kind"] == "Kafka")
        compact_connect = next(d["spec"] for d in compact_docs if d["kind"] == "KafkaConnect")
        assert compact_pool["replicas"] == compact_connect["replicas"] == 1
        assert "topologySpreadConstraints" not in compact_pool["template"]["pod"]
        assert compact_pool["storage"]["volumes"][0]["size"] == "20Gi"
        assert compact_kafka["kafka"]["config"]["log.retention.hours"] == 72
        assert compact_pool["storage"]["volumes"][0]["deleteClaim"] is False
        for key in ("default.replication.factor", "min.insync.replicas", "offsets.topic.replication.factor",
                    "transaction.state.log.replication.factor", "transaction.state.log.min.isr"):
            assert compact_kafka["kafka"]["config"][key] == 1
        for topic in (d["spec"] for d in compact_docs if d["kind"] == "KafkaTopic"):
            assert topic["replicas"] == topic["config"]["min.insync.replicas"] == 1
            if topic["config"]["cleanup.policy"] == "delete":
                assert topic["config"]["retention.ms"] == 259200000
            else:
                assert topic["config"]["cleanup.policy"] == "compact"
                assert "retention.ms" not in topic["config"]
        for key in ("config.storage.replication.factor", "offset.storage.replication.factor", "status.storage.replication.factor"):
            assert compact_connect["config"][key] == 1
        assert compact_kafka["kafka"]["listeners"][0]["tls"]
        assert compact_kafka["kafka"]["authorization"]["type"] == "simple"
        assert render(compact_profile) == []  # Profile alone must not deploy anything.
        measurement = copy.deepcopy(compact_profile)
        for key, value in yaml.safe_load((ROOT / "measurement-values.yaml").read_text(encoding="utf-8")).items():
            if isinstance(value, dict):
                measurement.setdefault(key, {}).update(value)
            else:
                measurement[key] = value
        measurement_docs = render(measurement)
        assert not any(d["kind"] == "KafkaConnect" for d in measurement_docs)
        measurement_kafka = next(d["spec"] for d in measurement_docs if d["kind"] == "Kafka")
        measurement_pool = next(d["spec"] for d in measurement_docs if d["kind"] == "KafkaNodePool")
        assert measurement_kafka["kafka"]["config"]["log.retention.hours"] == 72
        assert measurement_pool["replicas"] == 1 and measurement_pool["storage"]["volumes"][0]["size"] == "20Gi"
        assert measurement_pool["resources"]["requests"]["memory"] == "1536Mi"
        measurement_topic = next(d["spec"] for d in measurement_docs if d["kind"] == "KafkaTopic")
        assert measurement_topic["topicName"] == "infra-smoke" and measurement_topic["config"]["retention.ms"] == 259200000
        pipeline = copy.deepcopy(measurement)
        for key, value in yaml.safe_load((ROOT / "pipeline-smoke/runtime-values.yaml.example").read_text(encoding="utf-8")).items():
            if isinstance(value, dict):
                pipeline.setdefault(key, {}).update(value)
            else:
                pipeline[key] = value
        pipeline_docs = render(pipeline)
        assert not any(d["kind"] == "KafkaConnect" for d in pipeline_docs)
        assert {d["spec"]["topicName"] for d in pipeline_docs if d["kind"] == "KafkaTopic"} == {"infra-smoke", "infra-smoke.infra_smoke.events"}
        pipeline["connect"].update(enabled=True, image=full["connect"]["image"])
        pipeline_docs = render(pipeline)
        assert next(d["spec"]["replicas"] for d in pipeline_docs if d["kind"] == "KafkaConnect") == 1
        pipeline_connectors = list(yaml.safe_load_all((ROOT / "pipeline-smoke/connectors.yaml.example").read_text(encoding="utf-8")))
        for doc in pipeline_connectors:
            jsonschema.Draft7Validator(schemas["KafkaConnector"]).validate(doc)
            assert doc["metadata"]["labels"]["strimzi.io/cluster"] == pipeline["connect"]["name"]
        sink_prefix = next(doc["spec"]["config"]["topics.dir"] for doc in pipeline_connectors
                           if doc["spec"]["class"] == "io.confluent.connect.s3.S3SinkConnector")
        role_example = (ROOT / "pipeline-smoke/workload-access.tfvars.example").read_text(encoding="utf-8")
        assert f'"{sink_prefix}/" =' in role_example, "Trial S3 Sink output and IAM prefix must match"
        business = copy.deepcopy(compact_profile)
        for key, value in yaml.safe_load((ROOT / "cdc-orders-values.yaml").read_text(encoding="utf-8")).items():
            if isinstance(value, dict):
                business.setdefault(key, {}).update(value)
            else:
                business[key] = value
        render(business, error="connect.image digest is required")  # digest comes from runtime.local.yaml
        business["connect"]["image"] = full["connect"]["image"]
        business_docs = render(business)
        business_topics = {d["spec"]["topicName"]: d["spec"] for d in business_docs if d["kind"] == "KafkaTopic"}
        assert set(business_topics) == BUSINESS_TOPICS | {"debezium-heartbeat.cdc"} | {
            "clothes-query-dev-connect-" + s for s in ("configs", "offsets", "status")}
        assert "infra-smoke" not in business_topics
        for name in BUSINESS_TOPICS:
            assert business_topics[name]["partitions"] == 3 and business_topics[name]["replicas"] == 1
            assert business_topics[name]["config"]["retention.ms"] == 259200000
        assert not any(d["kind"] == "KafkaUser" and d["metadata"]["name"] == "infra-smoke-client" for d in business_docs)
        business_pool = next(d["spec"] for d in business_docs if d["kind"] == "KafkaNodePool")
        measurement_pool_doc = next(d for d in measurement_docs if d["kind"] == "KafkaNodePool")
        assert business_pool == measurement_pool_doc["spec"], "Business upgrade must not change the broker pool/PVC"
        business_connect = next(d["spec"] for d in business_docs if d["kind"] == "KafkaConnect")
        assert business_connect["replicas"] == 1
        ui_user = next(d for d in business_docs if d["kind"] == "KafkaUser" and d["metadata"]["name"] == "kafka-ui")
        for acl in ui_user["spec"]["authorization"]["acls"]:
            assert not set(acl["operations"]) & {"Write", "Create", "Delete", "Alter", "AlterConfigs", "All"}
        ui_deploy = next(d for d in business_docs if d["kind"] == "Deployment")
        ui_env = {e["name"]: e.get("value") for e in ui_deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert ui_env["KAFKA_CLUSTERS_0_READONLY"] == "true"
        assert ui_env["KAFKA_CLUSTERS_0_PROPERTIES_SECURITY_PROTOCOL"] == "SSL"
        assert "@sha256:" in ui_deploy["spec"]["template"]["spec"]["containers"][0]["image"]
        assert ui_deploy["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] is True
        assert next(d for d in business_docs if d["kind"] == "Service")["spec"]["type"] == "ClusterIP"
        ui_policy = next(d for d in business_docs if d["kind"] == "NetworkPolicy")
        assert ui_policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8083}]
        business_listener = next(d["spec"] for d in business_docs if d["kind"] == "Kafka")["kafka"]["listeners"][0]
        assert {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "kafka-ui"}}} in business_listener["networkPolicyPeers"]
        assert not any(d["kind"] in UI_KINDS for d in compact_docs)  # ui is off by default
        bad = copy.deepcopy(business); bad["ui"]["image"] = ""
        render(bad, error="ui.image digest is required")
        bad = copy.deepcopy(business); bad["ui"]["image"] = "ghcr.io/kafbat/kafka-ui:latest"
        render(bad, error="image")
        bad = copy.deepcopy(business); bad["ui"]["topics"] = ["unknown"]
        render(bad, error="UI ACL references an undefined")
        bad = copy.deepcopy(business); bad["ui"]["topics"] = []
        render(bad, error="ui.topics requires")
        bad = copy.deepcopy(business); bad["ui"]["name"] = "clothes-query-dev-connect"
        render(bad, error="Duplicate or reserved ui name")
        render({"ui": {"enabled": True}}, error="ui requires kafka.enabled")
        budget = [compact_pool["resources"], compact_connect["resources"],
                  compact_kafka["entityOperator"]["topicOperator"]["resources"],
                  compact_kafka["entityOperator"]["userOperator"]["resources"],
                  yaml.safe_load((ROOT / "operator-values.yaml").read_text())["resources"]]
        def memory_mib(value):
            return int(value[:-2]) * (1024 if value.endswith("Gi") else 1)
        assert sum(memory_mib(r["requests"]["memory"]) for r in budget) == 3456
        assert sum(memory_mib(r["limits"]["memory"]) for r in budget) == 3840
        bad_compact = copy.deepcopy(compact); bad_compact["kafka"]["replicas"] = 3
        render(bad_compact, error="replicas")
        bad_compact = copy.deepcopy(compact); bad_compact["connect"]["replicas"] = 2
        render(bad_compact, error="replicas")
        render({"connect": {"replicas": 1}}, error="replicas")
        render({"profile": "unknown"}, error="profile")
        monitored = copy.deepcopy(full)
        monitored["metrics"] = {"enabled": True, "lagExporter": {
            "enabled": True, "topicRegex": "^example-orders$", "groupRegex": "^example-reader$"}}
        monitored_docs = render(monitored)
        configmap = next(d for d in monitored_docs if d["kind"] == "ConfigMap")
        monitored_kafka = next(d["spec"] for d in monitored_docs if d["kind"] == "Kafka")
        monitored_connect = next(d["spec"] for d in monitored_docs if d["kind"] == "KafkaConnect")
        for spec, key in [(monitored_kafka["kafka"], "kafka.yml"), (monitored_connect, "connect.yml")]:
            ref = spec["metricsConfig"]["valueFrom"]["configMapKeyRef"]
            assert ref == {"name": configmap["metadata"]["name"], "key": key}
            assert spec["metricsConfig"]["type"] == "jmxPrometheusExporter"
        assert monitored_kafka["kafkaExporter"]["topicRegex"] == "^example-orders$"
        assert monitored_kafka["kafkaExporter"]["groupRegex"] == "^example-reader$"
        metrics_only = copy.deepcopy(base); metrics_only["metrics"] = {"enabled": True}
        metrics_only_docs = render(metrics_only)
        assert not any(d["kind"] == "KafkaConnect" for d in metrics_only_docs)
        assert "kafkaExporter" not in next(d["spec"] for d in metrics_only_docs if d["kind"] == "Kafka")
        cdc = copy.deepcopy(full)
        cdc["topics"][0].update(name="smoke.public.cdc_probe", resourceName="smoke-public-cdc-probe")
        cdc["clients"][0]["consumeTopics"] = ["smoke.public.cdc_probe"]
        cdc["connect"]["produceTopics"] = ["smoke.public.cdc_probe"]
        cdc_docs = render(cdc)
        assert any(d["kind"] == "KafkaTopic" and d["metadata"]["name"] == "smoke-public-cdc-probe"
                   and d["spec"]["topicName"] == "smoke.public.cdc_probe" for d in cdc_docs)
        sink = copy.deepcopy(cdc)
        sink["connect"].update(consumeTopics=["smoke.public.cdc_probe"], consumerGroups=["connect-smoke-s3"])
        sink_docs = render(sink)
        sink_user = next(d for d in sink_docs if d["kind"] == "KafkaUser" and d["metadata"]["name"] == "clothes-query-dev-connect")
        acls = sink_user["spec"]["authorization"]["acls"]
        assert any(a["resource"] == {"type": "topic", "name": "smoke.public.cdc_probe", "patternType": "literal"}
                   and a["operations"] == ["Read", "Describe"] for a in acls)
        assert any(a["resource"] == {"type": "group", "name": "connect-smoke-s3", "patternType": "literal"}
                   and a["operations"] == ["Read"] for a in acls)
        bad_sink = copy.deepcopy(sink); bad_sink["connect"]["consumeTopics"] = ["unknown"]
        render(bad_sink, error="Connect ACL references an undefined")
        bad_sink = copy.deepcopy(sink); bad_sink["connect"]["consumerGroups"] = []
        render(bad_sink, error="Connect consumers require explicit consumerGroups")
        bad_sink = copy.deepcopy(sink); bad_sink["connect"]["consumerGroups"] = ["*"]
        render(bad_sink, error="consumerGroups")
        kafka = next(d["spec"]["kafka"] for d in docs if d["kind"] == "Kafka")
        listener = kafka["listeners"][0]
        assert listener["type"] == "internal" and listener["tls"]
        assert listener["authentication"]["type"] == "tls"
        assert kafka["authorization"]["type"] == "simple"
        assert not kafka["config"]["auto.create.topics.enable"]
        pool = next(d["spec"] for d in docs if d["kind"] == "KafkaNodePool")
        assert pool["replicas"] == 3 and set(pool["roles"]) == {"controller", "broker"}
        spread = pool["template"]["pod"]["topologySpreadConstraints"][0]
        assert spread["minDomains"] == 2 and spread["maxSkew"] == 1
        assert spread["whenUnsatisfiable"] == "DoNotSchedule"
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
            ({"kafka": {"enabled": True, "storageGi": None}}, "kafka.storageGi is required"),
            ({"kafka": {"enabled": True, "storageGi": 100, "retentionHours": None}}, "kafka.retentionHours is required"),
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
        bad = copy.deepcopy(cdc); del bad["topics"][0]["resourceName"]
        render(bad, error="DNS-compatible resourceName")
        bad = copy.deepcopy(cdc); bad["topics"].append({"name": "other", "resourceName": "smoke-public-cdc-probe", "partitions": 1, "retentionMs": 1000})
        render(bad, error="Duplicate KafkaTopic resourceName")
        render({"metrics": {"enabled": True}}, error="metrics requires kafka.enabled")
        render({"metrics": {"lagExporter": {"enabled": True}}}, error="lagExporter requires metrics.enabled")
        bad = copy.deepcopy(full); bad["metrics"] = {"enabled": True, "lagExporter": {"enabled": True}}
        render(bad, error="explicit topicRegex and groupRegex")
        bad = copy.deepcopy(monitored); bad["metrics"]["lagExporter"]["topicRegex"] = "["
        render(bad, error="mustRegexMatch")

        for suffix in ("configs", "offsets", "status"):
            bad = copy.deepcopy(full)
            bad["topics"][0]["resourceName"] = "clothes-query-dev-connect-" + suffix
            render(bad, error="Reserved KafkaTopic resourceName")

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
        assert storage["allowVolumeExpansion"] is True
        jobs = yaml.safe_load((ROOT / "metrics" / "scrape-jobs.yaml").read_text())
        fixtures = [
            {"__meta_kubernetes_pod_label_strimzi_io_cluster": "clothes-query-dev-kafka",
             "__meta_kubernetes_pod_label_strimzi_io_pool_name": "combined"},
            {"__meta_kubernetes_pod_label_strimzi_io_name": "clothes-query-dev-connect-connect"},
            {"__meta_kubernetes_pod_label_strimzi_io_name": "clothes-query-dev-kafka-kafka-exporter"},
        ]
        assert len(jobs) == 3 and len({j["job_name"] for j in jobs}) == 3
        for index, job in enumerate(jobs):
            assert job["kubernetes_sd_configs"] == [{"role": "pod", "namespaces": {"names": ["kafka"]}}]
            def selected(labels):
                return all(re.fullmatch(rule["regex"], ";".join(labels.get(k, "") for k in rule["source_labels"]))
                           for rule in job["relabel_configs"] if rule.get("action") == "keep")
            for other, fixture in enumerate(fixtures):
                labels = {**fixture, "__meta_kubernetes_pod_phase": "Running",
                          "__meta_kubernetes_pod_container_port_name": "tcp-prometheus"}
                assert bool(selected(labels)) == (index == other)
                assert not selected({**labels, "__meta_kubernetes_pod_container_port_name": "rest-api"})
                assert not selected({**labels, "__meta_kubernetes_pod_phase": "Pending"})
    print(f"PASS: lint, standard/single-node/CDC/Sink/pipeline/metrics rendering, {len(docs)} base CRs and monitored CRs against Strimzi 1.3.0 schemas, business CDC/UI values, 35 rejected inputs, operator/storage checks")
    print("Single-node Kafka/Connect/operator budget: requests 3456Mi, limits 3840Mi; excludes Kubernetes/CSI/app/Spark resources.")
    print("No Kubernetes/AWS connection, apply, push or runtime claim.")


if __name__ == "__main__":
    main()
