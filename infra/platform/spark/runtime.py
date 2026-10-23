"""Render Spark execution scaffolding only. Never contact AWS or Kubernetes."""
import argparse
import json
import re
from pathlib import Path

import yaml


def validate_names(namespace="spark", name_prefix="spark", node_pool=None):
    for value, limit in [(namespace, 63), (name_prefix, 45), (node_pool, 63)]:
        if value is not None and (len(value) > limit or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", value)):
            raise ValueError("Use a DNS label within the namespace/prefix/node-pool length limit")


def pod_template(name, placement, *, name_prefix="spark", node_pool=None):
    validate_names(name_prefix=name_prefix, node_pool=node_pool)
    pool = node_pool or "clothes-query-dev-compute" + ("-spark" if placement == "dedicated" else "")
    spec = {
        "serviceAccountName": name_prefix + "-" + name,
        "automountServiceAccountToken": name == "driver",
        "nodeSelector": {"karpenter.sh/nodepool": pool},
        "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{"name": "spark-main", "securityContext": {
            "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
        }}],
    }
    if placement == "dedicated":
        spec["tolerations"] = [{"key": "clothes-query/dedicated", "operator": "Equal", "value": "spark", "effect": "NoSchedule"}]
    if name == "driver":
        spec["volumes"] = [{"name": "infra", "configMap": {"name": name_prefix + "-runtime"}}]
        spec["containers"][0]["volumeMounts"] = [{"name": "infra", "mountPath": "/opt/spark/infra", "readOnly": True}]
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"labels": {"app.kubernetes.io/part-of": name_prefix + "-runtime"}}, "spec": spec}


def properties(placement, *, namespace="spark", name_prefix="spark"):
    validate_names(namespace, name_prefix)
    # Small development profile; Python/Hadoop/S3 dependencies belong to the image owner.
    settings = {
        "spark.kubernetes.namespace": namespace,
        "spark.kubernetes.authenticate.driver.serviceAccountName": name_prefix + "-driver",
        "spark.kubernetes.authenticate.executor.serviceAccountName": name_prefix + "-executor",
        "spark.kubernetes.driver.podTemplateFile": "/opt/spark/infra/driver-pod-template.yaml",
        "spark.kubernetes.executor.podTemplateFile": "/opt/spark/infra/executor-pod-template.yaml",
        "spark.kubernetes.driver.podTemplateContainerName": "spark-main",
        "spark.kubernetes.executor.podTemplateContainerName": "spark-main",
        "spark.driver.cores": "1",
        "spark.kubernetes.driver.request.cores": "250m" if placement == "dedicated" else "100m",
        "spark.kubernetes.driver.limit.cores": "1",
        "spark.driver.memory": "512m",
        "spark.driver.memoryOverhead": "512m",
        "spark.executor.instances": "1",
        "spark.executor.cores": "1",
        "spark.kubernetes.executor.request.cores": "500m",
        "spark.kubernetes.executor.limit.cores": "1",
        "spark.executor.memory": "1g",
        "spark.executor.memoryOverhead": "512m",
        "spark.dynamicAllocation.enabled": "false",
        "spark.sql.shuffle.partitions": "4",
        "spark.kubernetes.submission.waitAppCompletion": "true",
    }
    if placement == "dedicated":
        settings.update({
            "spark.dynamicAllocation.enabled": "true",
            "spark.dynamicAllocation.minExecutors": "1",
            "spark.dynamicAllocation.initialExecutors": "1",
            "spark.dynamicAllocation.maxExecutors": "2",
            "spark.dynamicAllocation.shuffleTracking.enabled": "true",
        })
    return "\n".join(f"{k} {v}" for k, v in settings.items()) + "\n"


def resources(placement="dedicated", *, namespace="spark", name_prefix="spark", node_pool=None, existing_namespace=False):
    validate_names(namespace, name_prefix, node_pool)
    if placement not in {"dedicated", "shared-memory"}:
        raise ValueError("Unknown placement")
    objects = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}]
    def obj(kind, name, **extra):
        return {"apiVersion": "rbac.authorization.k8s.io/v1" if kind in {"Role", "RoleBinding"} else "v1",
                "kind": kind, "metadata": {"name": name, "namespace": namespace}, **extra}
    for name in ["submitter", "driver", "executor"]:
        objects.append(obj("ServiceAccount", name_prefix + "-" + name, automountServiceAccountToken=name != "executor"))
    for name in ["submitter", "driver"]:
        objects.append(obj("Role", name_prefix + "-" + name, rules=[
            {"apiGroups": [""], "resources": ["pods", "services", "configmaps"], "verbs": ["create", "get", "list", "watch", "patch", "update", "delete"]},
            {"apiGroups": [""], "resources": ["pods/log", "events"], "verbs": ["get", "list", "watch"]},
        ]))
        if name == "submitter":
            # Spark 4.2's NetworkPolicyFeatureStep applies an executor ingress policy.
            objects[-1]["rules"].append({
                "apiGroups": ["networking.k8s.io"], "resources": ["networkpolicies"],
                "verbs": ["create", "get", "patch", "delete"],
            })
        objects.append(obj("RoleBinding", name_prefix + "-" + name,
            subjects=[{"kind": "ServiceAccount", "name": name_prefix + "-" + name, "namespace": namespace}],
            roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name_prefix + "-" + name}))
    launcher = "airflow-" + name_prefix + "-launcher"
    objects.append(obj("Role", launcher, rules=[
        {"apiGroups": [""], "resources": ["pods"], "verbs": ["create", "get", "list", "watch", "patch", "delete"]},
        {"apiGroups": [""], "resources": ["pods/log", "events"], "verbs": ["get", "list", "watch"]},
        {"apiGroups": ["batch"], "resources": ["jobs"], "verbs": ["create", "get", "list", "watch", "patch", "delete"]},
    ]))
    objects.append(obj("RoleBinding", launcher,
        subjects=[{"kind": "ServiceAccount", "name": "airflow-scheduler", "namespace": "airflow"}],
        roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": launcher}))
    objects.append(obj("ResourceQuota", name_prefix + "-budget", spec={"hard": {
        "requests.cpu": "3", "requests.memory": "6Gi", "limits.cpu": "4", "limits.memory": "6Gi", "pods": "4",
    }}))
    objects.append(obj("ConfigMap", name_prefix + "-runtime", data={
        "spark.properties": properties(placement, namespace=namespace, name_prefix=name_prefix),
        **{name + "-pod-template.yaml": yaml.safe_dump(pod_template(name, placement, name_prefix=name_prefix, node_pool=node_pool), sort_keys=False) for name in ["driver", "executor"]},
    }))
    if existing_namespace:
        # Shared namespace ownership/quota belongs to the platform owner, not one job.
        objects = [obj for obj in objects if obj["kind"] not in {"Namespace", "ResourceQuota"}]
    return objects


def submission_job(image, app_file, name, placement, application_args=(), *, namespace="spark", name_prefix="spark", node_pool=None):
    validate_names(namespace, name_prefix, node_pool)
    if not re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Supply an immutable application image with sha256 digest")
    if not re.fullmatch(r"local:///[-a-zA-Z0-9_./]+\.(py|jar)", app_file) or ".." in app_file:
        raise ValueError("Application must be a local:/// image path ending in .py or .jar")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,38}[a-z0-9]", name):
        raise ValueError("Use a DNS-safe run name of 2 to 40 characters")
    pool = node_pool or "clothes-query-dev-compute" + ("-spark" if placement == "dedicated" else "")
    spec = {
        "restartPolicy": "Never", "serviceAccountName": name_prefix + "-submitter",
        "nodeSelector": {"karpenter.sh/nodepool": pool},
        "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
        "volumes": [{"name": "infra", "configMap": {"name": name_prefix + "-runtime"}}],
        "containers": [{"name": "submit", "image": image,
            "env": [{"name": "SPARK_DRIVER_MEMORY", "value": "512m"}],
            "command": ["/opt/spark/bin/spark-submit"],
            "args": ["--master", "k8s://https://kubernetes.default.svc:443", "--deploy-mode", "cluster", "--name", name,
                "--properties-file", "/opt/spark/infra/spark.properties",
                "--conf", "spark.kubernetes.container.image=" + image,
                "--conf", "spark.kubernetes.driver.pod.name=" + name + "-driver", app_file, *application_args],
            "volumeMounts": [{"name": "infra", "mountPath": "/opt/spark/infra", "readOnly": True}],
            "resources": {"requests": {"cpu": "250m" if placement == "dedicated" else "100m", "memory": "512Mi"}, "limits": {"cpu": "500m", "memory": "1Gi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
        }],
    }
    if placement == "dedicated":
        spec["tolerations"] = [{"key": "clothes-query/dedicated", "operator": "Equal", "value": "spark", "effect": "NoSchedule"}]
    return {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": namespace},
            "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 600, "template": {"spec": spec}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placement", choices=["dedicated", "shared-memory"], default="dedicated")
    parser.add_argument("--namespace", default="spark")
    parser.add_argument("--name-prefix", default="spark")
    parser.add_argument("--node-pool")
    parser.add_argument("--existing-namespace", action="store_true", help="Do not manage a shared Namespace or its ResourceQuota")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-job", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--application-file")
    parser.add_argument("--run-name", default="spark-trial")
    parser.add_argument("--application-arg", action="append", default=[])
    args = parser.parse_args()
    options = dict(namespace=args.namespace, name_prefix=args.name_prefix, node_pool=args.node_pool)
    objects = resources(args.placement, existing_namespace=args.existing_namespace, **options)
    if args.include_job:
        if not args.image or not args.application_file:
            parser.error("--include-job requires --image and --application-file")
        objects.append(submission_job(args.image, args.application_file, args.run_name, args.placement, args.application_arg, **options))
    elif args.image or args.application_file or args.application_arg:
        parser.error("Use --include-job explicitly to render a workload")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump_all(objects, sort_keys=False), encoding="utf-8")
    print(json.dumps({"rendered": len(objects), "placement": args.placement, "includes_job": args.include_job, "applied": False}))


if __name__ == "__main__":
    main()
