"""One-shot read-only incident checks. Never restart, apply, delete or query business rows."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
from urllib.parse import urlencode

CONTEXT = "clothes-query-dev"
ACCOUNT = "827913617635"
MIB = 1024 ** 2


def command(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
    if p.returncode:
        raise RuntimeError("Read request failed; verify access and connectivity")
    return p.stdout


def aws(*args):
    return json.loads(command(["aws", *args, "--region", "ap-northeast-1", "--output", "json", "--no-cli-pager"]))


def kube(*args):
    return command(["kubectl", "--context", CONTEXT, "--request-timeout=20s", *args])


def point_status(points, statistic, threshold, now, *, below=False):
    if not points:
        return "UNKNOWN", None
    point = max(points, key=lambda p: p["Timestamp"])
    at = datetime.fromisoformat(point["Timestamp"].replace("Z", "+00:00"))
    age = (now - at).total_seconds()
    if age < 0 or age > 900 or statistic not in point:
        return "UNKNOWN", None
    value = float(point[statistic])
    if not math.isfinite(value):
        return "UNKNOWN", None
    return ("WARN" if (value < threshold if below else value >= threshold) else "OK"), value


def object_status(objects, complete, now, max_age):
    if not objects:
        return ("WARN" if complete else "UNKNOWN"), None
    last = max(datetime.fromisoformat(x["LastModified"].replace("Z", "+00:00")) for x in objects)
    age = (now - last).total_seconds()
    if age < 0:
        return "UNKNOWN", None
    if age <= max_age:
        return "OK", round(age)
    return ("WARN" if complete else "UNKNOWN"), round(age)


def main():
    global CONTEXT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly perform read-only Kubernetes/AWS requests")
    parser.add_argument("--expect-ingestion", action="store_true", help="Enable Bronze freshness checks only when input is expected")
    parser.add_argument("--rds-instance", default="clothes-query-dev-rds")
    parser.add_argument("--bucket", default="clothes-query-datalake")
    parser.add_argument("--kube-context", default=CONTEXT)
    parser.add_argument("--wal-budget-mib", type=int, default=256)
    parser.add_argument("--s3-max-age-minutes", type=int, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pipeline", action="store_true", help="Also inspect runtime resources, v2 collector, Gold B objects and Airflow run metadata")
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    parser.add_argument("--node-memory-warn-percent", type=float, default=85)
    parser.add_argument("--node-cpu-warn-percent", type=float, default=90)
    parser.add_argument("--ledger-max-age-minutes", type=int, default=3)
    parser.add_argument("--dag-max-age-minutes", type=int, default=15)
    parser.add_argument("--gold-b-ingest-prefix", default="gold-b-ingest")
    parser.add_argument("--reprocess-dags", nargs="+", default=["gold_b_reprocess", "silver_gold_a_reprocess"])
    args = parser.parse_args()
    CONTEXT = args.kube_context
    if not args.live:
        parser.error("Specify --live to perform read-only checks")
    if args.wal_budget_mib <= 0 or args.s3_max_age_minutes <= 0:
        parser.error("Thresholds must be positive")
    if not (0 < args.node_memory_warn_percent <= 100 and 0 < args.node_cpu_warn_percent <= 100) or args.ledger_max_age_minutes <= 0 or args.dag_max_age_minutes <= 0:
        parser.error("Runtime thresholds must be positive; percentages cannot exceed 100")
    if not args.gold_b_ingest_prefix:
        parser.error("Gold B Pod name prefix cannot be empty")
    now = datetime.now(timezone.utc)
    rows = []
    cluster_verified = False
    def add(name, status, detail):
        rows.append({"check": name, "status": status, "detail": detail})
    def attempt(name, operation):
        try:
            operation()
        except (RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError, subprocess.TimeoutExpired):
            add(name, "UNKNOWN", "Read failed or data unavailable; not a healthy result")

    def check_kubernetes():
        nonlocal cluster_verified
        # Context names may be aliases; verify the actual Tokyo cluster endpoint.
        if kube("config", "current-context").strip() != CONTEXT:
            raise ValueError("Unexpected context")
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise ValueError("Unexpected account")
        endpoint = aws("eks", "describe-cluster", "--name", "clothes-query-dev-eks")["cluster"]["endpoint"]
        config = json.loads(kube("config", "view", "--minify", "-o", "json"))
        if config["clusters"][0]["cluster"]["server"].rstrip("/") != endpoint.rstrip("/"):
            raise ValueError("Unexpected cluster endpoint")
        cluster_verified = True
        for ns, prefixes in {"kafka": ["clothes-query-dev-kafka-combined-", "clothes-query-dev-connect-connect-"],
                             "airflow": ["airflow-api-server-", "airflow-scheduler-", "airflow-dag-processor-"],
                             "monitoring": ["monitoring-prometheus-", "monitoring-grafana-"]}.items():
            pods = json.loads(kube("get", "pods", "-n", ns, "-o", "json"))["items"]
            for prefix in prefixes:
                matches = [p for p in pods if p["metadata"]["name"].startswith(prefix) and not p["metadata"].get("deletionTimestamp")]
                ready = sum(p.get("status", {}).get("phase") == "Running" and any(c.get("type") == "Ready" and c.get("status") == "True" for c in p["status"].get("conditions", [])) for p in matches)
                add(ns + "/" + prefix.rstrip("-"), "OK" if matches and ready == len(matches) else "WARN", {"ready_pods": ready, "total_pods": len(matches), "scope": "pod readiness only"})
            if ns == "kafka":
                for pod in pods:
                    if pod["metadata"].get("labels", {}).get("strimzi.io/pool-name") != "combined":
                        continue
                    pvc_volumes = {v["name"] for v in pod["spec"].get("volumes", []) if "persistentVolumeClaim" in v}
                    mounts = [m["mountPath"] for c in pod["spec"]["containers"] if c["name"] == "kafka" for m in c.get("volumeMounts", [])
                              if m["name"] in pvc_volumes and m["mountPath"].startswith("/var/lib/kafka/data-")]
                    if not mounts:
                        add("KafkaDisk", "UNKNOWN", "No confirmed persistent data mount")
                    for mount in mounts:
                        output = kube("exec", "-n", "kafka", pod["metadata"]["name"], "-c", "kafka", "--", "df", "-Pk", mount)
                        percent = int(output.splitlines()[-1].split()[-2].rstrip("%"))
                        add("KafkaDisk", "WARN" if percent >= 80 else "OK", {"pod": pod["metadata"]["name"], "used_percent": percent})
    attempt("Kubernetes", check_kubernetes)

    def check_prometheus():
        if not cluster_verified:
            raise ValueError("Cluster identity was not verified")
        for name, expr in [("CDCConnected", 'min(debezium_postgres_connected{context="streaming"})'),
                           ("ConnectTasks", 'sum(kafka_connect_task_status{status!="running"} == 1) or (count(kafka_connect_task_status) * 0)'),
                           ("PrometheusAlerts", 'count(ALERTS{alertstate="firing"}) or vector(0)')]:
            path = "/api/v1/namespaces/monitoring/services/http:monitoring-prometheus:9090/proxy/api/v1/query?" + urlencode({"query": expr})
            data = json.loads(kube("get", "--raw", path))
            result = data.get("data", {}).get("result", []) if data.get("status") == "success" else []
            if not result:
                add(name, "UNKNOWN", "Metric unavailable")
            else:
                value = float(result[0]["value"][1])
                add(name, "UNKNOWN" if not math.isfinite(value) else "WARN" if (value != 1 if name == "CDCConnected" else value > 0) else "OK", value if math.isfinite(value) else None)
        # Task absence is a separate condition: empty sums must never imply health.
        path = "/api/v1/namespaces/monitoring/services/http:monitoring-prometheus:9090/proxy/api/v1/query?" + urlencode({"query": "count(kafka_connect_task_status)"})
        count = json.loads(kube("get", "--raw", path)).get("data", {}).get("result", [])
        add("ConnectTaskMetricsPresent", "OK" if count and float(count[0]["value"][1]) > 0 else "UNKNOWN", "Task metrics coverage")
    attempt("Prometheus", check_prometheus)

    def check_rds():
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise ValueError("Unexpected account")
        db = aws("rds", "describe-db-instances", "--db-instance-identifier", args.rds_instance)["DBInstances"][0]
        add("RDSAvailable", "OK" if db["DBInstanceStatus"] == "available" else "WARN", db["DBInstanceStatus"])
        add("RDSBackupConfiguration", "OK" if db.get("BackupRetentionPeriod", 0) >= 7 and db.get("LatestRestorableTime") else "WARN",
            {"retention_days": db.get("BackupRetentionPeriod"), "latest_restorable_time": db.get("LatestRestorableTime"), "restore_tested": False})
        for metric, stat, threshold, below in [("FreeStorageSpace", "Minimum", 2 * 1024 ** 3, True),
                                               ("OldestReplicationSlotLag", "Maximum", args.wal_budget_mib * MIB * 0.75, False)]:
            data = aws("cloudwatch", "get-metric-statistics", "--namespace", "AWS/RDS", "--metric-name", metric,
                       "--dimensions", "Name=DBInstanceIdentifier,Value=" + args.rds_instance,
                       "--start-time", (now - timedelta(minutes=30)).isoformat(), "--end-time", now.isoformat(),
                       "--period", "300", "--statistics", stat)
            status, value = point_status(data.get("Datapoints", []), stat, threshold, now, below=below)
            add("RDS/" + metric, status, {"bytes": value, "warning_threshold_bytes": threshold})
    attempt("RDS", check_rds)

    def check_s3():
        if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
            raise ValueError("Unexpected account")
        if aws("s3api", "get-bucket-location", "--bucket", args.bucket, "--expected-bucket-owner", ACCOUNT).get("LocationConstraint") != "ap-northeast-1":
            raise ValueError("Bucket is not in Tokyo")
        for prefix in ("bronze/orders/", "bronze/order-items/", "bronze/payments/"):
            objects, complete = [], True
            for date in (now, now - timedelta(days=1)):
                token = None
                for _ in range(3):
                    command_args = ["s3api", "list-objects-v2", "--bucket", args.bucket, "--expected-bucket-owner", ACCOUNT,
                                    "--prefix", prefix + date.strftime("year=%Y/month=%m/day=%d/"), "--max-keys", "1000", "--no-paginate"]
                    if token:
                        command_args += ["--continuation-token", token]
                    page = aws(*command_args)
                    objects.extend({"LastModified": x["LastModified"]} for x in page.get("Contents", []))
                    token = page.get("NextContinuationToken")
                    if not page.get("IsTruncated"):
                        break
                else:
                    complete = False
            status, age = object_status(objects, complete, now, args.s3_max_age_minutes * 60)
            if not args.expect_ingestion and status in {"OK", "WARN"}:
                status = "INFO"
            add("S3/" + prefix, status, {"last_observed_age_seconds": age, "scan_complete": complete,
                "input_expected": args.expect_ingestion, "scope": "object arrival within two UTC days, not business correctness"})
    attempt("S3", check_s3)
    if args.pipeline and cluster_verified:
        import runtime_checks
        rows.extend(runtime_checks.collect(kube, aws, datetime.now(timezone.utc), args, object_status))
    else:
        add("AirflowBusinessRuns", "UNKNOWN", "Pipeline checks disabled or cluster identity unverified")
    report = {"checked_at_utc": now.isoformat(), "read_only": True, "region": "ap-northeast-1", "checks": rows}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.format == "summary":
        import runtime_checks
        print(runtime_checks.summary(report))
    else:
        print(text)
    if args.pipeline:
        import runtime_checks
        return runtime_checks.exit_code(rows)
    return 1 if any(r["status"] == "WARN" for r in rows) else 2 if any(r["status"] == "UNKNOWN" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
