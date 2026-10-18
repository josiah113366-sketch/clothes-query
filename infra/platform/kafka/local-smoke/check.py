"""Run a disposable local-only CDC smoke test; never uses AWS, host ports or business data."""
import argparse
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import threading

ROOT = Path(__file__).resolve().parent
TOPIC = "smoke.public.cdc_probe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="Use single-node memory limits and 1-vCPU quotas for Kafka and Connect; fixtures run separately")
    parser.add_argument("--s3", action="store_true", help="Also test the S3 Sink against an isolated local Moto S3 fixture; never AWS")
    options = parser.parse_args()
    # Reject remote Docker contexts before any mutations or cleanup.
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "TF_", "KUBE"))}
    if clean_env.get("DOCKER_HOST") or clean_env.get("DOCKER_CONTEXT"):
        raise RuntimeError("Use a local Docker context without DOCKER_HOST/DOCKER_CONTEXT overrides")
    context = json.loads(subprocess.check_output(["docker", "context", "inspect"], env=clean_env, text=True))[0]
    host = context["Endpoints"]["docker"]["Host"]
    if not host.startswith(("npipe://", "unix://")):
        raise RuntimeError("Only a local Docker socket is supported")
    if subprocess.check_output(["docker", "info", "--format", "{{.OSType}}"], env=clean_env, text=True).strip() != "linux":
        raise RuntimeError("Start Docker Desktop Linux engine first")
    project = "cq-cdc-" + secrets.token_hex(5)
    print("Local test project: " + project, flush=True)
    image = project + "-connect:local"
    base_image = project + "-cdc-base:local" if options.s3 else image
    admin_password, cdc_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    def redact(value):
        return value.replace(admin_password, "[redacted]").replace(cdc_password, "[redacted]")

    def docker(*args, stdin=None, timeout=90, check=True):
        # Bytes preserve LF when a Linux shell reads stdin from a Windows Python process.
        result = subprocess.run(["docker", *map(str, args)], input=None if stdin is None else stdin.encode("utf-8"),
                                capture_output=True, env=clean_env, timeout=timeout)
        result.stdout = result.stdout.decode("utf-8", errors="replace")
        result.stderr = result.stderr.decode("utf-8", errors="replace")
        if check and result.returncode:
            raise RuntimeError(redact(result.stderr[-2500:] or result.stdout[-2500:]))
        return result

    with tempfile.TemporaryDirectory(prefix=project + "-") as temp:
        directory = Path(temp)
        database_dir = directory / "database"
        database_dir.mkdir()
        tls_dir = directory / "tls"
        tls_dir.mkdir()
        (database_dir / "username").write_text("cdc_user", encoding="utf-8")
        (database_dir / "password").write_text(cdc_password, encoding="utf-8")
        worker = (ROOT / "worker.properties").read_text().replace("bootstrap.servers=kafka:9092", "bootstrap.servers=kafka:9093")
        for prefix in ["", "producer.", "consumer.", "admin."]:
            for key, value in {"security.protocol": "SSL", "ssl.truststore.type": "PEM",
                               "ssl.truststore.location": "/mnt/tls/ca.crt", "ssl.keystore.type": "PEM",
                               "ssl.keystore.location": "/mnt/tls/identity.pem",
                               "ssl.endpoint.identification.algorithm": "https"}.items():
                worker += f"\n{prefix}{key}={value}"
        worker_path = directory / "worker.properties"
        worker_path.write_text(worker + "\n", encoding="utf-8")
        clean_env.update(SMOKE_ADMIN_PASSWORD=admin_password, SMOKE_CONNECT_IMAGE=image,
                         SMOKE_SECRET_DIR=str(database_dir), SMOKE_TLS_DIR=str(tls_dir),
                         SMOKE_WORKER_CONFIG=str(worker_path))
        extra_compose = []
        if options.s3:
            extra_compose += ["--file", ROOT / "s3/compose.yaml"]
        if options.compact:
            override = directory / "compact.json"
            override.write_text(json.dumps({"services": {
                "kafka": {"cpus": 1.0, "mem_limit": "1536m"},
                "connect": {"cpus": 1.0, "mem_limit": "1024m"}
            }}), encoding="utf-8")
            extra_compose += ["--file", override]

        def compose(*args, **kwargs):
            # Kafka CLI JVMs must not bind the broker's already active javaagent port.
            if args[:3] == ("exec", "-T", "kafka") and str(args[3]).startswith("/opt/kafka/bin/"):
                args = args[:3] + ("env", "KAFKA_OPTS=",) + args[3:]
            return docker("compose", "--project-name", project, "--file", ROOT / "compose.yaml", *extra_compose, *args, **kwargs)

        def sql(statement):
            return compose("exec", "-T", "postgres", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
                           "-U", "postgres", "-d", "smoke", "-At", stdin=statement).stdout.strip()

        def until(description, function, timeout=120, ignore_stopped=()):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    result = function()
                    if result:
                        return result
                except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired):
                    pass
                states = compose("ps", "--all", "--format", "json").stdout
                for line in states.splitlines():
                    if not line.startswith("{"):
                        continue
                    state = json.loads(line)
                    if state.get("State") in {"exited", "dead"} and state["Service"] not in ignore_stopped:
                        raise RuntimeError("Local service exited during " + description + ": " + state["Service"])
                time.sleep(2)
            raise RuntimeError("Timed out: " + description)

        def rest(path, payload=None):
            args = ["exec", "-T", "connect", "curl", "--fail", "--silent", "--show-error", "--max-time", "5"]
            if payload is not None:
                args += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
            return json.loads(compose(*args, "http://localhost:8083" + path,
                                      stdin=None if payload is None else json.dumps(payload), timeout=15).stdout)

        def running():
            status = rest("/connectors/smoke-postgres/status")
            return status["connector"]["state"] == "RUNNING" and bool(status["tasks"]) and all(t["state"] == "RUNNING" for t in status["tasks"])

        def events():
            result = compose("exec", "-T", "client", "/opt/kafka/bin/kafka-console-consumer.sh",
                             "--bootstrap-server", "kafka:9093", "--consumer.config", "/mnt/tls/reader.properties",
                             "--topic", TOPIC, "--from-beginning",
                             "--partition", "0", "--timeout-ms", "10000" if options.compact else "3000",
                             timeout=60 if options.compact else 20, check=False)
            parsed = []
            for line in result.stdout.splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and isinstance(record.get("payload"), dict):
                    parsed.append(record["payload"])
            return parsed

        def has(records, op, row_id, value):
            field = "before" if op == "d" else "after"
            return any(e.get("op") == op and e.get(field) == {"id": row_id, "value": value} for e in records)

        def stored_offsets():
            result = compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-console-consumer.sh",
                             "--bootstrap-server", "kafka:9092", "--topic", "smoke-connect-offsets", "--partition", "0",
                             "--from-beginning", "--timeout-ms", "3000", "--property", "print.key=true",
                             "--property", "key.separator=\t", timeout=20, check=False)
            latest = {}
            for line in result.stdout.splitlines():
                if "\t" not in line:
                    continue
                key, value = line.split("\t", 1)
                try:
                    parsed_key, parsed_value = json.loads(key), json.loads(value)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed_key, list) and parsed_key[0] == "smoke-postgres":
                    latest[json.dumps(parsed_key, sort_keys=True)] = parsed_value
            return latest

        def kafka_container():
            container_id = compose("ps", "--quiet", "kafka").stdout.strip()
            inspected = json.loads(docker("inspect", container_id).stdout)[0]
            volume = next(m["Name"] for m in inspected["Mounts"] if m["Destination"] == "/var/lib/cq-kafka" and m["Type"] == "volume")
            return container_id, volume

        def metrics(service):
            return compose("exec", "-T", service, "curl", "--fail", "--silent", "--show-error",
                           "--max-time", "10", "http://localhost:9404/metrics", timeout=20).stdout

        def metric_values(text, name, labels=()):
            values = []
            for line in text.splitlines():
                match = re.match(r"^" + re.escape(name) + r"(?:\{([^}]*)\})?\s+(\S+)", line)
                if match and all(label in (match[1] or "") for label in labels):
                    values.append(float(match[2]))
            return values

        samples = []
        stop_samples = threading.Event()
        def sample_resources():
            while not stop_samples.is_set():
                try:
                    ids = compose("ps", "--quiet", timeout=10, check=False).stdout.split()
                    if ids:
                        result = docker("stats", "--no-stream", "--format", "{{json .}}", *ids, timeout=10, check=False)
                        samples.extend(json.loads(line) for line in result.stdout.splitlines() if line.startswith("{"))
                except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
                    pass
                stop_samples.wait(2)
        sampler = threading.Thread(target=sample_resources, daemon=True)
        cleanup_error = None
        try:
            print("Building pinned Connect image for isolated local test...", flush=True)
            docker("build", "--platform", "linux/amd64", "--tag", base_image,
                   ROOT.parent / "connect-image", timeout=300)
            if options.s3:
                docker("build", "--platform", "linux/amd64", "--build-arg", "BASE_IMAGE=" + base_image,
                       "--tag", image, ROOT / "s3", timeout=300)
            generator_uid = os.getuid() if hasattr(os, "getuid") else 1001
            docker("run", "--interactive", "--rm", "--user", f"{generator_uid}:0", "--network", "none", "--mount", f"type=bind,source={tls_dir},target=/work",
                   "--entrypoint", "/bin/bash", image, "-s", stdin=(ROOT / "make-tls.sh").read_text(), timeout=60)
            compose("config", "--quiet")
            compose("run", "--rm", "--no-deps", "kafka-data-init")
            compose("up", "--detach", "postgres", "kafka", timeout=300)
            if options.compact:
                sampler.start()
            until("PostgreSQL ready", lambda: compose("exec", "-T", "postgres", "pg_isready", "-U", "postgres").returncode == 0)
            until("Kafka ready", lambda: compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh",
                                                "--bootstrap-server", "kafka:9092", "--list", timeout=15).returncode == 0)
            print("DB and Kafka ready; preparing restricted test scope...", flush=True)
            sql(f"""
                CREATE ROLE cdc_user WITH LOGIN REPLICATION PASSWORD '{cdc_password}';
                GRANT CONNECT ON DATABASE smoke TO cdc_user;
                CREATE TABLE public.cdc_probe (id integer PRIMARY KEY, value integer NOT NULL);
                CREATE TABLE public.cdc_excluded (id integer PRIMARY KEY);
                ALTER TABLE public.cdc_probe REPLICA IDENTITY FULL;
                GRANT USAGE ON SCHEMA public TO cdc_user;
                GRANT SELECT ON public.cdc_probe TO cdc_user;
                CREATE PUBLICATION smoke_publication FOR TABLE public.cdc_probe;
                INSERT INTO public.cdc_probe VALUES (1, 10);
            """)
            assert sql("SELECT rolreplication AND NOT rolsuper FROM pg_roles WHERE rolname='cdc_user';") == "t"
            for topic in [TOPIC, "smoke-connect-configs", "smoke-connect-offsets", "smoke-connect-status"]:
                args = ["exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092",
                        "--create", "--topic", topic, "--partitions", "1", "--replication-factor", "1"]
                if topic != TOPIC:
                    args += ["--config", "cleanup.policy=compact"]
                compose(*args)
            def acl(principal, resource_flag, resource_name, operations):
                args = ["exec", "-T", "kafka", "/opt/kafka/bin/kafka-acls.sh", "--bootstrap-server", "kafka:9092",
                        "--add", "--allow-principal", "User:CN=" + principal, resource_flag, resource_name,
                        "--resource-pattern-type", "literal"]
                for operation in operations:
                    args += ["--operation", operation]
                compose(*args)
            for topic in ["smoke-connect-configs", "smoke-connect-offsets", "smoke-connect-status"]:
                acl("smoke-connect", "--topic", topic, ["Read", "Write", "Describe", "DescribeConfigs"])
            acl("smoke-connect", "--topic", TOPIC, ["Write", "Describe"])
            acl("smoke-connect", "--group", "smoke-connect", ["Read"])
            compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-acls.sh", "--bootstrap-server", "kafka:9092",
                    "--add", "--allow-principal", "User:CN=smoke-connect", "--cluster", "--operation", "IdempotentWrite")
            acl("smoke-reader", "--topic", TOPIC, ["Read", "Describe"])
            acl("smoke-reader", "--group", "smoke-reader", ["Read"])
            compose("up", "--detach", "connect", "client", timeout=120)
            until("Connect REST ready", lambda: rest("/"))
            plugins = rest("/connector-plugins")
            assert any(p["class"] == "io.debezium.connector.postgresql.PostgresConnector" and p["version"] == "3.7.0.Final" for p in plugins)
            rest("/connectors", {"name": "smoke-postgres", "config": {
                "connector.class": "io.debezium.connector.postgresql.PostgresConnector", "tasks.max": "1",
                "database.hostname": "postgres", "database.port": "5432", "database.dbname": "smoke",
                "database.user": "${directory:/mnt/cdc-database:username}",
                "database.password": "${directory:/mnt/cdc-database:password}",
                "database.sslmode": "disable", "plugin.name": "pgoutput", "topic.prefix": "smoke",
                "table.include.list": r"public\.cdc_probe", "publication.name": "smoke_publication",
                "publication.autocreate.mode": "disabled", "slot.name": "smoke_slot",
                "snapshot.mode": "initial", "slot.drop.on.stop": "false"
            }})
            until("Connector RUNNING", running)
            until("Initial snapshot", lambda: has(events(), "r", 1, 10))
            for identity in ["no-cert", "wrong"]:
                rejected = compose("exec", "-T", "client", "/opt/kafka/bin/kafka-console-consumer.sh",
                                   "--bootstrap-server", "kafka:9093", "--consumer.config", f"/mnt/tls/{identity}.properties",
                                   "--topic", TOPIC, "--partition", "0", "--from-beginning", "--timeout-ms", "5000",
                                   timeout=20, check=False)
                assert "SSLHandshakeException" in rejected.stdout + rejected.stderr or "SslAuthenticationException" in rejected.stdout + rejected.stderr, identity
            forbidden = "smoke-denied"
            compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092",
                    "--create", "--topic", forbidden, "--partitions", "1", "--replication-factor", "1")
            for denied_topic, group, error in [(forbidden, None, "TopicAuthorizationException"),
                                                (TOPIC, "denied-group", "GroupAuthorizationException")]:
                args = ["exec", "-T", "client", "/opt/kafka/bin/kafka-console-consumer.sh", "--bootstrap-server", "kafka:9093",
                        "--consumer.config", "/mnt/tls/reader.properties", "--topic", denied_topic, "--from-beginning", "--timeout-ms", "5000"]
                args += ["--group", group] if group else ["--partition", "0"]
                rejected = compose(*args, timeout=20, check=False)
                assert error in rejected.stdout + rejected.stderr, error
            allowed = compose("exec", "-T", "client", "/opt/kafka/bin/kafka-console-consumer.sh", "--bootstrap-server", "kafka:9093",
                              "--consumer.config", "/mnt/tls/reader.properties", "--topic", TOPIC, "--from-beginning",
                              "--group", "smoke-reader", "--max-messages", "1", "--timeout-ms", "10000", timeout=25)
            assert '"op":"r"' in allowed.stdout
            print("PASS: mTLS/hostname and allowed topic/group; missing/rogue certificates and forbidden topic/group rejected", flush=True)
            sql("INSERT INTO public.cdc_probe VALUES (2,20); UPDATE public.cdc_probe SET value=11 WHERE id=1; DELETE FROM public.cdc_probe WHERE id=2; INSERT INTO public.cdc_excluded VALUES (99);")
            def changes_received():
                data = events()
                return all(has(data, *expected) for expected in [("c", 2, 20), ("u", 1, 11), ("d", 2, 20)])
            until("Insert/update/delete delivered", changes_received)
            print("PASS: snapshot and insert/update/delete delivered; dedicated non-superuser and mounted credentials", flush=True)
            if options.compact:
                started = time.monotonic()
                sql("INSERT INTO public.cdc_probe SELECT i, i FROM generate_series(1000,1999) AS i;")
                def bulk_received():
                    ids = {e["after"]["id"] for e in events() if e.get("op") == "c" and e.get("after") and 1000 <= e["after"]["id"] <= 1999}
                    return len(ids) == 1000
                until("Compact 1000-row burst", bulk_received, timeout=180)
                print(f"PASS: compact 1000-row CDC burst delivered in {time.monotonic() - started:.1f}s (includes polling/consumer startup)", flush=True)
            compose("stop", "--timeout", "20", "connect")
            assert sql("SELECT NOT active FROM pg_replication_slots WHERE slot_name='smoke_slot';") == "t"
            sql("INSERT INTO public.cdc_probe VALUES (3,30);")
            compose("start", "connect")
            until("Connector resumed", running)
            until("Change made while Connect was stopped", lambda: has(events(), "c", 3, 30))
            topics = compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092", "--list").stdout.splitlines()
            assert TOPIC in topics and not any("cdc_excluded" in topic for topic in topics)
            print("PASS: change during Connect outage delivered after restart; excluded table produced no topic", flush=True)
            compose("stop", "--timeout", "20", "connect")
            offsets_before = stored_offsets()
            assert offsets_before and all(isinstance(v, dict) and v.get("lsn", 0) > 0 for v in offsets_before.values())
            end_before = compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-get-offsets.sh",
                                 "--bootstrap-server", "kafka:9092", "--topic", TOPIC, "--time", "-1").stdout.strip()
            before_id, before_volume = kafka_container()
            compose("up", "--detach", "--force-recreate", "--no-deps", "kafka", timeout=120)
            until("Recreated Kafka ready", lambda: compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh",
                                                         "--bootstrap-server", "kafka:9092", "--list", timeout=15).returncode == 0,
                  ignore_stopped=("connect",))
            after_id, after_volume = kafka_container()
            assert before_id != after_id and before_volume == after_volume
            end_after = compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-get-offsets.sh",
                                "--bootstrap-server", "kafka:9092", "--topic", TOPIC, "--time", "-1").stdout.strip()
            assert end_before and end_before == end_after
            assert offsets_before == stored_offsets()
            sql("INSERT INTO public.cdc_probe VALUES (4,40);")
            compose("start", "connect")
            until("Connector recovered from persisted config", running)
            until("CDC resumed without new snapshot", lambda: has(events(), "c", 4, 40))
            retained = events()
            assert all(has(retained, *expected) for expected in [("r", 1, 10), ("c", 2, 20), ("u", 1, 11), ("d", 2, 20), ("c", 3, 30)])
            print("PASS: new Kafka container reused its volume; messages/Connect offsets retained and CDC resumed", flush=True)
            kafka_metrics = metrics("kafka")
            assert metric_values(kafka_metrics, "jmx_scrape_error") == [0]
            assert metric_values(kafka_metrics, "kafka_controller_active_controller_count") == [1]
            assert metric_values(kafka_metrics, "kafka_server_replicamanager_underreplicatedpartitions") == [0]
            def connect_metrics_ready():
                text = metrics("connect")
                return (metric_values(text, "jmx_scrape_error") == [0]
                        and metric_values(text, "kafka_connect_task_status", ['status="running"']) == [1]
                        and metric_values(text, "debezium_postgres_connected", ['context="streaming"']) == [1])
            until("Connect/CDC JMX metrics", connect_metrics_ready)
            compose("exec", "-T", "kafka", "/opt/kafka/bin/kafka-consumer-groups.sh",
                    "--bootstrap-server", "kafka:9092", "--group", "smoke-lag", "--topic", TOPIC,
                    "--reset-offsets", "--to-earliest", "--execute")
            compose("up", "--detach", "lag-exporter", timeout=60)
            def lag_ready():
                text = metrics("lag-exporter")
                values = metric_values(text, "kafka_consumergroup_lag", ['consumergroup="smoke-lag"', 'topic="' + TOPIC + '"'])
                return bool(values) and all(v > 0 for v in values)
            until("Consumer lag metric", lag_ready)
            print("PASS: Kafka replication/controller, Connect task/CDC connection and positive consumer lag metrics served", flush=True)
            if options.s3:
                print("Testing CDC events through the S3 Sink into local-only object storage...", flush=True)
                compose("up", "--detach", "s3", timeout=180)
                probe_code = (ROOT / "s3/probe.py").read_text(encoding="utf-8")
                def s3_probe(mode, check=True):
                    return compose("exec", "-T", "s3", "python", "-", mode,
                                   stdin=probe_code, timeout=60, check=check)
                until("Local S3 fixture ready", lambda: s3_probe("init").returncode == 0)
                assert any(p["class"] == "io.confluent.connect.s3.S3SinkConnector" for p in plugins)
                acl("smoke-connect", "--topic", TOPIC, ["Read"])
                acl("smoke-connect", "--group", "connect-smoke-s3", ["Read"])
                rest("/connectors", {"name": "smoke-s3", "config": {
                    "connector.class": "io.confluent.connect.s3.S3SinkConnector", "tasks.max": "1",
                    "topics": TOPIC, "s3.bucket.name": "cq-pipeline-smoke", "s3.region": "us-east-1",
                    "store.url": "http://s3:5000", "s3.path.style.access.enabled": "true",
                    "topics.dir": "infra-smoke", "flush.size": "1",
                    "storage.class": "io.confluent.connect.s3.storage.S3Storage",
                    "format.class": "io.confluent.connect.s3.format.json.JsonFormat",
                    "partitioner.class": "io.confluent.connect.storage.partitioner.DefaultPartitioner",
                    "schema.compatibility": "NONE", "behavior.on.null.values": "ignore",
                    "key.converter": "org.apache.kafka.connect.json.JsonConverter",
                    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                    "key.converter.schemas.enable": "true", "value.converter.schemas.enable": "true"
                }})
                def sink_running():
                    status = rest("/connectors/smoke-s3/status")
                    return (status["connector"]["state"] == "RUNNING" and bool(status["tasks"])
                            and all(t["state"] == "RUNNING" for t in status["tasks"]))
                until("S3 Sink RUNNING", sink_running)
                until("Snapshot/create/update/delete JSON in local S3", lambda: s3_probe("initial").returncode == 0)
                compose("stop", "--timeout", "20", "connect")
                sql("INSERT INTO public.cdc_probe VALUES (5,50);")
                compose("start", "connect")
                until("CDC restarted with Sink", running)
                until("Sink restarted with persisted config", sink_running)
                until("Change during outage reached local S3", lambda: s3_probe("resumed").returncode == 0)
                result = json.loads(s3_probe("resumed").stdout)
                pipeline_report = {"scope": "local PostgreSQL -> mTLS Kafka -> Confluent S3 Sink -> Moto S3; not AWS",
                                   "snapshot_create_update_delete": True, "resumed_after_connect_outage": True,
                                   "objects": result["objects"], "records": result["records"],
                                   "duplicates_allowed": True, "aws_iam_verified": False}
                report = ROOT.parents[3] / ".cache/kafka-pipeline-report.json"
                report.write_text(json.dumps(pipeline_report, indent=2), encoding="utf-8")
                print("PASS: snapshot/create/update/delete stored as JSON; restart replay reached isolated prefix; report=" + str(report), flush=True)
            if options.compact:
                ids = compose("ps", "--quiet").stdout.split()
                inspected = json.loads(docker("inspect", *ids).stdout)
                health = [{"service": c["Config"]["Labels"]["com.docker.compose.service"],
                           "oomKilled": c["State"]["OOMKilled"], "restartCount": c["RestartCount"],
                           "memoryLimit": c["HostConfig"]["Memory"], "nanoCpus": c["HostConfig"]["NanoCpus"]} for c in inspected]
                assert not any(c["oomKilled"] or c["restartCount"] for c in health)
                assert sum(c["nanoCpus"] for c in health if c["service"] in {"kafka", "connect"}) == 2_000_000_000
                assert sum(c["memoryLimit"] for c in health) < 8 * 1024**3
                report = ROOT.parents[3] / ".cache" / "kafka-compact-report.json"
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps({"project": project, "health": health, "samples": samples,
                                              "scope": "Kafka/Connect CPU quotas total 2 vCPU; fixtures outside budget; local CDC" + (" and local Moto S3 Sink" if options.s3 else "") + "; no Strimzi operator, Kubernetes, EKS, EBS, RDS TLS, AWS S3/IAM or Spark"}, indent=2), encoding="utf-8")
                print("PASS: Kafka/Connect quota sum 2 vCPU; test fixtures outside CPU budget; memory limits below 8Gi; no OOM/restarts; report=" + str(report), flush=True)
        except Exception as error:
            if options.compact:
                failure = {"project": project, "error": redact(str(error)), "samples": samples}
                for service in ("kafka", "connect", "client"):
                    try:
                        failure[service + "Logs"] = redact(compose("logs", "--no-color", "--tail", "100", service, timeout=20, check=False).stdout)
                    except (RuntimeError, subprocess.TimeoutExpired):
                        pass
                report = ROOT.parents[3] / ".cache" / "kafka-compact-failure.json"
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps(failure, indent=2), encoding="utf-8")
            raise
        finally:
            stop_samples.set()
            if sampler.is_alive():
                sampler.join(timeout=25)
            # Only resources in this invocation's random Compose project are removed.
            result = compose("down", "--volumes", "--remove-orphans", "--timeout", "20", timeout=120, check=False)
            if result.returncode:
                cleanup_error = redact(result.stderr[-2000:])
            docker("image", "rm", image, timeout=30, check=False)
            if base_image != image:
                docker("image", "rm", base_image, timeout=30, check=False)
            if cleanup_error:
                raise RuntimeError("Local test cleanup failed for " + project + ": " + cleanup_error)
            print("Cleaned this test's containers/network/volume/image tag.", flush=True)


if __name__ == "__main__":
    main()
