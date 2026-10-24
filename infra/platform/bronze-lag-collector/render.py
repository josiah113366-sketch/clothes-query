"""Render collector-only access/runtime objects. No cluster or AWS calls."""
import argparse
import json
from pathlib import Path
import re

NS = "pipelines"
NAME = "gold-b-lag-collector"
KAFKA = "clothes-query-dev-kafka"
CONNECT = "clothes-query-dev-connect"
TOPICS = ("clickstream", "members-events", "orders", "order-items", "payments")


def access():
    user = {"apiVersion": "kafka.strimzi.io/v1", "kind": "KafkaUser",
            "metadata": {"name": NAME, "namespace": "kafka", "labels": {"strimzi.io/cluster": KAFKA}},
            "spec": {"authentication": {"type": "tls"}, "authorization": {"type": "simple", "acls": [
                *[{"resource": {"type": "topic", "name": topic, "patternType": "literal"}, "operations": ["Read", "Describe"]} for topic in TOPICS],
                {"resource": {"type": "group", "name": "connect-bronze-s3-sink-v2", "patternType": "literal"}, "operations": ["Describe"]},
                {"resource": {"type": "group", "name": "gold-b-lag-", "patternType": "prefix"}, "operations": ["Read", "Describe"]},
            ]}}}
    policies = []
    for suffix, selector, port in [
        ("kafka", {"strimzi.io/name": KAFKA + "-kafka", "strimzi.io/cluster": KAFKA}, 9093),
        ("connect", {"strimzi.io/cluster": CONNECT, "strimzi.io/kind": "KafkaConnect"}, 8083),
    ]:
        policies.append({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                         "metadata": {"name": NAME + "-to-" + suffix, "namespace": "kafka"},
                         "spec": {"podSelector": {"matchLabels": selector}, "policyTypes": ["Ingress"],
                                  "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": NS}},
                                                         "podSelector": {"matchLabels": {"app": NAME}}}],
                                               "ports": [{"port": port, "protocol": "TCP"}]}]}})
    return [user, *policies]


def runtime(image):
    if not re.fullmatch(r"827913617635\.dkr\.ecr\.ap-northeast-1\.amazonaws\.com/clothes-query-dev/gold-b-lag-collector@sha256:[0-9a-f]{64}", image):
        raise ValueError("Supply the reviewed collector ECR digest")
    env = {"AWS_REGION": "ap-northeast-1", "AWS_DEFAULT_REGION": "ap-northeast-1", "AWS_EC2_METADATA_DISABLED": "true",
           "GOLD_B_LAG_OUTPUT": "s3://clothes-query-datalake/gold_b/bronze_lag_snapshots/",
           "KAFKA_BOOTSTRAP": KAFKA + "-kafka-bootstrap.kafka.svc.cluster.local:9093", "KAFKA_SECURITY_PROTOCOL": "SSL",
           "KAFKA_SSL_CA_FILE": "/etc/kafka/tls/ca.crt", "KAFKA_SSL_CERT_FILE": "/etc/kafka/tls/user.crt",
           "KAFKA_SSL_KEY_FILE": "/etc/kafka/tls/user.key", "GOLD_B_CONNECT_URL": "http://" + CONNECT + "-connect-api.kafka.svc.cluster.local:8083",
           "GOLD_B_SINK_CONNECTOR": "bronze-s3-sink-v2", "GOLD_B_SINK_GROUP": "connect-bronze-s3-sink-v2", "GOLD_B_LAG_TOPICS": ",".join(TOPICS)}
    sa = {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": NAME, "namespace": NS}, "automountServiceAccountToken": False}
    cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": NAME, "namespace": NS}, "data": env}
    deployment = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": NAME, "namespace": NS},
                  "spec": {"replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": {"app": NAME}},
                           "template": {"metadata": {"labels": {"app": NAME}}, "spec": {
                               "serviceAccountName": NAME, "automountServiceAccountToken": False,
                               "nodeSelector": {"karpenter.sh/nodepool": "clothes-query-dev-api"},
                               "tolerations": [{"key": "clothes-query/dedicated", "operator": "Equal", "value": "api", "effect": "NoSchedule"}],
                               "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001, "fsGroup": 10001, "seccompProfile": {"type": "RuntimeDefault"}},
                               "containers": [{"name": "collector", "image": image, "args": ["--interval", "60"],
                                               "envFrom": [{"configMapRef": {"name": NAME}}],
                                               "resources": {"requests": {"cpu": "25m", "memory": "128Mi"}, "limits": {"cpu": "250m", "memory": "384Mi"}},
                                               "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                                               "volumeMounts": [{"name": "tls", "mountPath": "/etc/kafka/tls", "readOnly": True}, {"name": "tmp", "mountPath": "/tmp"}]}],
                               "volumes": [{"name": "tls", "secret": {"secretName": NAME + "-tls", "defaultMode": 288}}, {"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}}]}}}}
    return [sa, cm, deployment]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    objects = access() + (runtime(args.image) if args.image else [])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": objects}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rendered": len(objects), "includes_runtime": bool(args.image), "applied": False}))


if __name__ == "__main__":
    main()
