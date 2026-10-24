"""Additional one-shot pipeline checks. No workload creation or business writes."""
from datetime import datetime, timezone
import json
import re


def quantity(value, resource):
    value = str(value)
    units = {"n": 1e-6, "u": 1e-3, "m": 1, "": 1000} if resource == "cpu" else {
        "Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 ** 2,
        "K": 1000 / 1024 ** 2, "M": 1e6 / 1024 ** 2, "G": 1e9 / 1024 ** 2, "": 1 / 1024 ** 2,
    }
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([a-zA-Z]*)", value)
    if not match or match[2] not in units:
        raise ValueError("Unsupported resource quantity")
    return float(match[1]) * units[match[2]]


def pod_request(pod, resource):
    def request(container):
        return quantity(container.get("resources", {}).get("requests", {}).get(resource, "0"), resource)
    spec = pod["spec"]
    regular = sum(request(c) for c in spec["containers"])
    sidecars = peak = 0
    for container in spec.get("initContainers", []):
        current = request(container)
        if container.get("restartPolicy") == "Always":
            sidecars += current
            peak = max(peak, sidecars)
        else:
            peak = max(peak, sidecars + current)
    effective = max(regular + sidecars, peak)
    override = spec.get("resources", {}).get("requests", {}).get(resource)
    if override is not None:
        effective = quantity(override, resource)
    return effective + quantity(spec.get("overhead", {}).get(resource, "0"), resource)


def ready(pod):
    return not pod["metadata"].get("deletionTimestamp") and any(
        c["type"] == "Ready" and c["status"] == "True" for c in pod.get("status", {}).get("conditions", [])
    )


def dag_status(dag, now, max_age_seconds):
    if dag is None:
        return "WAITING", {"reason": "DAG not registered"}
    if dag["paused"]:
        return "WAITING", {"reason": "DAG is paused; not enabled by this check"}
    latest = dag.get("latest", [])
    if latest and latest[0]["state"] == "failed":
        return "WARN", {"reason": "Latest run failed"}
    if not dag.get("last_success"):
        return "UNKNOWN", {"reason": "No successful run observed"}
    at = datetime.fromisoformat(dag["last_success"].replace("Z", "+00:00"))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    age = (now - at).total_seconds()
    if age < 0:
        return "UNKNOWN", {"reason": "Success timestamp is in the future"}
    return ("WARN" if age > max_age_seconds else "OK"), {
        "last_success_age_seconds": round(age), "latest_state": latest[0]["state"] if latest else None,
        "scope": "run status only; not business correctness",
    }


def exit_code(rows):
    for status, code in [("WARN", 1), ("UNKNOWN", 2), ("WAITING", 3)]:
        if any(r["status"] == status for r in rows):
            return code
    return 0


def ledger_status(objects, complete, now, max_age, expected, allow_empty, object_status):
    status, age = object_status(objects, complete, now, max_age)
    if not expected and status == "WARN":
        status = "INFO" if objects or allow_empty else "WAITING"
    return status, age


def summary(report):
    counts = {s: sum(r["status"] == s for r in report["checks"]) for s in ["OK", "INFO", "WAITING", "UNKNOWN", "WARN"]}
    lines = ["Tokyo pipeline status: " + ", ".join(f"{k}={v}" for k, v in counts.items())]
    lines += [f"[{r['status']:<7}] {r['check']}: " + (r["detail"] if isinstance(r["detail"], str) else json.dumps(r["detail"], ensure_ascii=False)) for r in report["checks"]]
    lines.append("WAITING=not connected/paused; UNKNOWN=not verified. No changes were applied.")
    return "\n".join(lines)


def collect(kube, aws, now, args, object_status):
    rows = []
    def add(name, status, detail):
        rows.append({"check": name, "status": status, "detail": detail})
    def attempt(name, fn):
        try:
            fn()
        except Exception:
            # CLI stderr, task logs, query results and credentials never become report details.
            add(name, "UNKNOWN", "Read failed; inspect access/connectivity separately")
    def get(kind, namespace=None):
        command = ["get", kind, "-o", "json"]
        command += ["-n", namespace] if namespace else ["-A"] if kind == "pods" else []
        return json.loads(kube(*command))["items"]
    pods = []
    def check_nodes():
        nonlocal pods
        nodes = get("nodes")
        pods = get("pods")
        active = [p for p in pods if p.get("status", {}).get("phase") not in {"Succeeded", "Failed"}]
        add("NodeCount", "INFO", {"total": len(nodes), "pools": {
            pool: sum(n["metadata"]["labels"].get("karpenter.sh/nodepool") == pool for n in nodes)
            for pool in sorted({n["metadata"]["labels"].get("karpenter.sh/nodepool", "unlabelled") for n in nodes})
        }})
        for node in nodes:
            name = node["metadata"]["name"]
            conditions = {c["type"]: c["status"] for c in node["status"]["conditions"]}
            add("Node/" + name, "OK" if conditions.get("Ready") == "True" and all(
                conditions.get(c) == "False" for c in ["MemoryPressure", "DiskPressure", "PIDPressure"]
            ) else "WARN", {"conditions": conditions, "cpu_request_m": round(sum(
                pod_request(p, "cpu") for p in active if p["spec"].get("nodeName") == name)),
                "memory_request_mi": round(sum(pod_request(p, "memory") for p in active if p["spec"].get("nodeName") == name))})
        for ns in ["airflow", "kafka", "dashboard", "agent", "pipelines", "monitoring", "argocd", "api"]:
            selected = [p for p in active if p["metadata"]["namespace"] == ns]
            if not selected:
                continue
            add("Pods/" + ns, "OK" if all(ready(p) for p in selected) else "WARN", {
                "ready": sum(ready(p) for p in selected), "total": len(selected),
                "restarts_since_pod_creation": sum(c.get("restartCount", 0) for p in selected for c in p.get("status", {}).get("containerStatuses", [])),
                "scope": "current Pods; historical evictions/deletions not counted",
            })
    attempt("RuntimeNodes", check_nodes)
    def check_usage():
        alloc = {n["metadata"]["name"]: n["status"]["allocatable"] for n in get("nodes")}
        metrics = json.loads(kube("get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"))["items"]
        if not metrics:
            raise ValueError("No metrics")
        observed = set()
        for node in metrics:
            name = node["metadata"]["name"]
            at = datetime.fromisoformat(node["timestamp"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - at).total_seconds()
            if age < 0 or age > 180:
                add("Usage/" + name, "UNKNOWN", "Stale/future node metrics")
                observed.add(name)
                continue
            cpu = quantity(node["usage"]["cpu"], "cpu") / quantity(alloc[name]["cpu"], "cpu") * 100
            memory = quantity(node["usage"]["memory"], "memory") / quantity(alloc[name]["memory"], "memory") * 100
            add("Usage/" + name, "WARN" if cpu >= args.node_cpu_warn_percent or memory >= args.node_memory_warn_percent else "OK", {
                "cpu_percent": round(cpu, 1), "memory_percent": round(memory, 1),
                "memory_mi": round(quantity(node["usage"]["memory"], "memory")), "scope": "instantaneous; not historical peak",
            })
            observed.add(name)
        for missing in set(alloc) - observed:
            add("Usage/" + missing, "UNKNOWN", "Node metrics missing")
    attempt("RuntimeUsage", check_usage)
    def check_connectors():
        connectors = get("kafkaconnectors", "kafka")
        expected = {"cdc-source", "bronze-s3-sink", "bronze-s3-sink-v2"}
        seen = set()
        for connector in connectors:
            name = connector["metadata"]["name"]
            if name not in expected:
                continue
            seen.add(name)
            status = connector.get("status", {})
            state = status.get("connectorStatus", {}).get("connector", {}).get("state")
            tasks = [t.get("state") for t in status.get("connectorStatus", {}).get("tasks", [])]
            current = status.get("observedGeneration") == connector["metadata"]["generation"]
            add("Connector/" + name, "UNKNOWN" if not current else "OK" if state == "RUNNING" and tasks and all(t == "RUNNING" for t in tasks) else "WARN", {"connector": state, "tasks": tasks, "generation_current": current})
        for name in expected - seen:
            add("Connector/" + name, "WAITING", "Connector not registered")
    attempt("RuntimeConnectors", check_connectors)
    def check_collector():
        selected = [p for p in pods if p["metadata"]["namespace"] == "pipelines" and p["metadata"]["name"].startswith("gold-b-lag-collector-") and ready(p)]
        if len(selected) != 1:
            raise ValueError("Expected one ready collector")
        script = """import json,os,urllib.request
c=os.environ.get('GOLD_B_SINK_CONNECTOR','bronze-s3-sink')
g=os.environ.get('GOLD_B_SINK_GROUP') or 'connect-'+c
url=os.environ.get('GOLD_B_CONNECT_URL','http://clothes-query-dev-connect-connect-api.kafka.svc.cluster.local:8083').rstrip('/')
with urllib.request.urlopen(url+'/connectors/'+c+'/status',timeout=15) as response:d=json.load(response)
print(json.dumps(dict(connector=c,group=g,state=d['connector']['state'],tasks=[t['state'] for t in d['tasks']])))
"""
        result = json.loads(kube("exec", selected[0]["metadata"]["name"], "-n", "pipelines", "--", "python", "-c", script))
        good = result["connector"] == "bronze-s3-sink-v2" and result["group"] == "connect-bronze-s3-sink-v2" and result["state"] == "RUNNING" and result["tasks"] and all(t == "RUNNING" for t in result["tasks"])
        add("CollectorV2Target", "OK" if good else "WARN", result)
    attempt("CollectorV2Target", check_collector)
    def check_catalog():
        tables = aws("glue", "get-tables", "--database-name", "gold_b")["TableList"]
        required = {"payment_states", "payment_conflicts", "payment_attempts", "malformed_messages"}
        views = {t["Name"] for t in tables if t.get("TableType") == "VIRTUAL_VIEW"}
        by_name = {t["Name"]: t for t in tables}
        required_columns = {"payment_events": {"cdc_op", "source_ts_ms", "rule_version"}, "malformed_events": {"record_key", "source_ts_ms"}}
        missing_columns = {name: sorted(columns - {c["Name"] for c in by_name.get(name, {}).get("StorageDescriptor", {}).get("Columns", [])}) for name, columns in required_columns.items()}
        missing_tables = sorted({"payment_events", "topic_messages", "bronze_lag_snapshots", "malformed_events"} - set(by_name))
        add("GoldBCatalog", "WAITING" if required - views or missing_tables or any(missing_columns.values()) else "OK", {"missing_views": sorted(required - views), "missing_tables": missing_tables, "missing_columns": missing_columns, "scope": "Glue metadata only; no Athena query"})
    attempt("GoldBCatalog", check_catalog)
    def check_ledgers():
        location = aws("s3api", "get-bucket-location", "--bucket", args.bucket, "--expected-bucket-owner", "827913617635").get("LocationConstraint")
        if location != "ap-northeast-1":
            raise ValueError("Bucket is not in Tokyo")
        ingest = [p for p in pods if p["metadata"]["namespace"] == "pipelines" and p["metadata"]["name"].startswith(args.gold_b_ingest_prefix) and not p["metadata"].get("deletionTimestamp") and p.get("status", {}).get("phase") != "Succeeded"]
        add("GoldBStreaming", "WAITING" if not ingest else "OK" if all(ready(p) for p in ingest) else "WARN", {"matching_pods": len(ingest), "configured_name_prefix": args.gold_b_ingest_prefix, "scope": "presence only; confirm final deployment name"})
        for name in ["payment_events", "topic_messages", "bronze_lag_snapshots", "malformed_events"]:
            objects, token, complete = [], None, False
            for _ in range(3):
                command = ["s3api", "list-objects-v2", "--bucket", args.bucket, "--expected-bucket-owner", "827913617635", "--prefix", "gold_b/" + name + "/", "--max-keys", "1000", "--no-paginate"]
                if token:
                    command += ["--continuation-token", token]
                page = aws(*command)
                objects.extend({"LastModified": o["LastModified"]} for o in page.get("Contents", []) if o["Size"] and o["Key"].endswith(".parquet"))
                token = page.get("NextContinuationToken")
                if not page.get("IsTruncated"):
                    complete = True
                    break
            # Error ledgers can legitimately stay empty. Stale data is an alarm only where new output is expected.
            expected = name == "bronze_lag_snapshots" or (bool(ingest) and args.expect_ingestion and name in {"payment_events", "topic_messages"})
            status, age = ledger_status(objects, complete, datetime.now(timezone.utc), args.ledger_max_age_minutes * 60, expected, name == "malformed_events", object_status)
            add("Ledger/" + name, status, {"parquet_objects_seen": len(objects), "scan_complete": complete, "latest_observed_age_seconds": age, "freshness_expected": expected, "scope": "object metadata; not business row counts"})
    attempt("GoldBLedgers", check_ledgers)
    def check_dags():
        schedulers = [p for p in pods if p["metadata"]["namespace"] == "airflow" and p["metadata"]["name"].startswith("airflow-scheduler-") and ready(p)]
        if len(schedulers) != 1:
            raise ValueError("Expected one ready scheduler")
        ids = ["agent_detection_5min", "agent_investigation_5min", *args.reprocess_dags]
        script = """import json
from airflow.settings import Session
from sqlalchemy import text
ids=IDS
out={}
with Session() as session:
 for name in ids:
  meta=session.execute(text('SELECT is_paused FROM dag WHERE dag_id=:name'),dict(name=name)).first()
  if meta is None:out[name]=None;continue
  latest=[dict(r) for r in session.execute(text('SELECT state,run_after FROM dag_run WHERE dag_id=:name ORDER BY run_after DESC LIMIT 3'),dict(name=name)).mappings()]
  success=session.execute(text("SELECT MAX(end_date) FROM dag_run WHERE dag_id=:name AND state='success'"),dict(name=name)).scalar()
  out[name]=dict(paused=bool(meta[0]),latest=latest,last_success=success)
print(json.dumps(out,default=str))
""".replace("ids=IDS", "ids=" + repr(ids))
        raw = kube("exec", schedulers[0]["metadata"]["name"], "-n", "airflow", "--", "python", "-c", script)
        data = json.loads(next(line for line in reversed(raw.splitlines()) if line.startswith("{")))
        for name in ids:
            if name in args.reprocess_dags:
                add("DAG/" + name, "WAITING" if data[name] is None else "INFO", {"registered": data[name] is not None, "scope": "registration only; request/completion contract not verified"})
            else:
                status, detail = dag_status(data[name], datetime.now(timezone.utc), args.dag_max_age_minutes * 60)
                add("DAG/" + name, status, detail)
    attempt("AirflowBusinessRuns", check_dags)
    return rows
