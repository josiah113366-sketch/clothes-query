"""Render Gold B access foundations only; never start jobs or contact AWS/Kubernetes."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re

import yaml

NS = "pipelines"
INGEST = "gold-b-ingest"
JOBS = "gold-b-ledger-jobs"
POOL = "gold_b_ledger"
NODE_POOL = "clothes-query-dev-compute-spark"
BUCKET = "clothes-query-datalake"
TOPICS = ("payments", "orders", "order-items", "members-events", "clickstream", "reviews.raw")
LEDGERS = ("payment_events", "topic_messages", "malformed_events")
TLS_SECRET = {INGEST: INGEST + "-tls", "gold-b-reprocess": "gold-b-reprocess-tls"}


def workload_bindings(existing, checkpoint_prefix=None):
    """Preserve every unrelated binding; do not infer the unconfirmed checkpoint."""
    result = copy.deepcopy(existing)
    bindings = result.setdefault("bindings", {})
    write = ["s3:GetObject", "s3:PutObject"]
    ingest_access = {"gold_b/" + table + "/": write.copy() for table in LEDGERS}
    unconfirmed_ingest_access = copy.deepcopy(ingest_access)
    if checkpoint_prefix is not None:
        if (not re.fullmatch(r"gold_b/_checkpoints/[a-zA-Z0-9/_=-]+/", checkpoint_prefix)
                or "//" in checkpoint_prefix):
            raise ValueError("Checkpoint must be an explicitly confirmed gold_b/_checkpoints/ child prefix")
        ingest_access[checkpoint_prefix] = write + ["s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
    additions = {INGEST + "-" + role: {"namespace": NS, "service_account": INGEST + "-" + role,
                "s3_access": copy.deepcopy(ingest_access)} for role in ("driver", "executor")}
    jobs_access = {"gold_b/" + table + "/": write + ["s3:DeleteObject"]
                   for table in (*LEDGERS, "bronze_lag_snapshots")}
    jobs_access["gold_b/reprocess_events/"] = write.copy()
    jobs_access.update({"bronze_v2/" + topic + "/": ["s3:GetObject"] for topic in TOPICS if topic != "reviews.raw"})
    additions[JOBS] = {"namespace": NS, "service_account": JOBS, "s3_access": jobs_access}
    for name, binding in additions.items():
        previous_without_checkpoint = {"namespace": NS, "service_account": name,
                                       "s3_access": unconfirmed_ingest_access}
        confirming_checkpoint = (checkpoint_prefix is not None and name in {INGEST + "-driver", INGEST + "-executor"}
                                 and bindings.get(name) == previous_without_checkpoint)
        if name in bindings and bindings[name] != binding and not confirming_checkpoint:
            raise ValueError("Review existing Gold B binding before changing it: " + name)
        if any(key != name and (value["namespace"], value["service_account"]) == (NS, name)
               for key, value in bindings.items()):
            raise ValueError("ServiceAccount is already managed under another binding")
        bindings[name] = binding
    return result


def shared_spark_conf(role):
    if role not in {"ingest", "batch"}:
        raise ValueError("Choose ingest or batch")
    return {
        "spark.dynamicAllocation.enabled": "false", "spark.dynamicAllocation.minExecutors": "1",
        "spark.dynamicAllocation.initialExecutors": "1", "spark.dynamicAllocation.maxExecutors": "1",
        "spark.executor.instances": "1", "spark.executor.cores": "1",
        "spark.kubernetes.driver.request.cores": "0.35" if role == "ingest" else "0.25",
        "spark.kubernetes.executor.request.cores": "0.5",
        "spark.kubernetes.driver.limit.cores": "1", "spark.kubernetes.executor.limit.cores": "1",
        "spark.driver.memory": "1g" if role == "ingest" else "512m",
        "spark.driver.memoryOverhead": "1g" if role == "ingest" else "768m",
        "spark.executor.memory": "768m", "spark.executor.memoryOverhead": "512m",
        "spark.sql.shuffle.partitions": "2",
    }


def foundation():
    source = Path(__file__).resolve().parents[1] / "spark" / "runtime.py"
    spec = importlib.util.spec_from_file_location("gold_b_spark_scaffold", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    objects = module.resources("dedicated", namespace=NS, name_prefix=INGEST,
                               node_pool=NODE_POOL, existing_namespace=True)
    cm = next(o for o in objects if o["kind"] == "ConfigMap")
    conf = dict(line.split(maxsplit=1) for line in cm["data"]["spark.properties"].splitlines())
    conf.update(shared_spark_conf("ingest"))
    conf["spark.kubernetes.driverEnv.PYTHONPATH"] = "/opt/gold_b"
    conf["spark.executorEnv.PYTHONPATH"] = "/opt/gold_b"
    cm["data"]["spark.properties"] = "".join(k + " " + v + "\n" for k, v in conf.items())
    for role in ("driver", "executor"):
        template = yaml.safe_load(cm["data"][role + "-pod-template.yaml"])
        template["spec"]["securityContext"].update({"runAsUser": 185, "runAsGroup": 185, "fsGroup": 185})
        template["metadata"].setdefault("labels", {})["app"] = INGEST
        template["spec"].setdefault("volumes", []).append({"name": "kafka-tls", "secret": {
            "secretName": TLS_SECRET[INGEST], "defaultMode": 288}})
        template["spec"]["containers"][0].setdefault("volumeMounts", []).append({
            "name": "kafka-tls", "mountPath": "/opt/kafka-tls", "readOnly": True})
        cm["data"][role + "-pod-template.yaml"] = yaml.safe_dump(template, sort_keys=False)
    objects.append({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": JOBS, "namespace": NS},
                    "automountServiceAccountToken": False})
    for user in TLS_SECRET:
        objects.append({"apiVersion": "kafka.strimzi.io/v1", "kind": "KafkaUser",
            "metadata": {"name": user, "namespace": "kafka", "labels": {"strimzi.io/cluster": "clothes-query-dev-kafka"}},
            "spec": {"authentication": {"type": "tls"}, "authorization": {"type": "simple", "acls": [
                *[{"resource": {"type": "topic", "name": topic, "patternType": "literal"},
                   "operations": ["Read", "Describe"]} for topic in TOPICS],
                {"resource": {"type": "group", "name": user + "-", "patternType": "prefix"},
                 "operations": ["Read", "Describe"]},
            ]}}})
    objects.append({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": {"name": "gold-b-jobs-to-kafka", "namespace": "kafka"},
        "spec": {"podSelector": {"matchLabels": {"strimzi.io/name": "clothes-query-dev-kafka-kafka",
                  "strimzi.io/cluster": "clothes-query-dev-kafka"}}, "policyTypes": ["Ingress"],
            "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": NS}},
                         "podSelector": {"matchLabels": {"app": name}}} for name in [INGEST, JOBS]],
                         "ports": [{"port": 9093, "protocol": "TCP"}]}]}})
    return objects


def pending_runtime():
    return {"image": None, "namespace": NS, "service_account": JOBS,
            "ledger_root": "s3://" + BUCKET + "/gold_b", "pool": POOL,
            "kafka_bootstrap": "clothes-query-dev-kafka-kafka-bootstrap.kafka.svc.cluster.local:9093",
            "kafka_tls_secret": TLS_SECRET["gold-b-reprocess"],
            "bronze_root": "s3://" + BUCKET + "/bronze_v2", "node_selector": {"karpenter.sh/nodepool": NODE_POOL}}


def pending_ingest(checkpoint_prefix=None):
    if checkpoint_prefix is not None:
        workload_bindings({}, checkpoint_prefix)
    return {"image": None, "namespace": NS, "submitter_service_account": INGEST + "-submitter",
            "driver_service_account": INGEST + "-driver", "executor_service_account": INGEST + "-executor",
            "runtime_configmap": INGEST + "-runtime",
            "application": "local:///opt/gold_b/pipelines/gold_b/jobs/streaming_ingest.py",
            "env": {"GOLD_B_LEDGER_ROOT": "s3://" + BUCKET + "/gold_b",
                    "GOLD_B_CHECKPOINT": "s3a://" + BUCKET + "/" + checkpoint_prefix if checkpoint_prefix else None,
                    "KAFKA_BOOTSTRAP": "clothes-query-dev-kafka-kafka-bootstrap.kafka.svc.cluster.local:9093",
                    "KAFKA_SECURITY_PROTOCOL": "SSL", "KAFKA_SSL_CA_FILE": "/opt/kafka-tls/ca.crt",
                    "KAFKA_SSL_CERT_FILE": "/opt/kafka-tls/user.crt", "KAFKA_SSL_KEY_FILE": "/opt/kafka-tls/user.key"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--existing-vars", type=Path)
    parser.add_argument("--checkpoint-prefix", help="Only after the exact S3 child prefix is confirmed")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "foundation.json").write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": foundation()}, indent=2), encoding="utf-8")
    (args.output_dir / "runtime.pending.json").write_text(json.dumps(pending_runtime(), indent=2), encoding="utf-8")
    (args.output_dir / "ingest.pending.json").write_text(json.dumps(pending_ingest(args.checkpoint_prefix), indent=2), encoding="utf-8")
    (args.output_dir / "batch-shared-spark-conf.json").write_text(json.dumps(shared_spark_conf("batch"), indent=2), encoding="utf-8")
    if args.existing_vars:
        values = json.loads(args.existing_vars.read_text(encoding="utf-8-sig"))
        (args.output_dir / "workload-access.tfvars.json").write_text(json.dumps(workload_bindings(values, args.checkpoint_prefix), indent=2), encoding="utf-8")
    print(json.dumps({"prepared": True, "workloads_started": 0, "checkpoint_permission": bool(args.checkpoint_prefix), "applied": False}))


if __name__ == "__main__":
    main()
