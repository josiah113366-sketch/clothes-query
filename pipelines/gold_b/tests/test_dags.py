"""Gold B DAG(infra/platform/airflow/dags/gold_b.py) 시험. Airflow 없이 가짜 모듈로 DAG 파일을 읽는다.

DAG 설정(주기·재시도·꺼진 채로 생성), Pod 명령·환경변수·Kafka 인증서, 같은 pool, 실행 설정 확인 규칙을 본다.
실제 Airflow에서 읽히는지와 Pod 실행은 인프라가 실행 설정(AIRFLOW_GOLD_B_RUNTIME)과 pool을 준비한 뒤 확인한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[3]
DAG_FILE = ROOT / "infra" / "platform" / "airflow" / "dags" / "gold_b.py"
# 예시 값 (실제 값은 인프라가 비공개 설정으로 공급한다)
RUNTIME = {
    "image": "registry.example/gold-b@sha256:" + "0" * 64,
    "namespace": "gold-b-jobs",
    "service_account": "gold-b-ledger",
    "ledger_root": "s3://example-bucket/gold_b",
    "kafka_bootstrap": "kafka.example:9093",
    "kafka_tls_secret": "gold-b-kafka-tls",
    "pool": "gold_b_ledger",
}


# ---------- 가짜 Airflow·Kubernetes 모듈 ----------

class FakeDag:
    def __init__(self, settings):
        self.settings = settings
        self.tasks = []


BUILDING: list[FakeDag] = []   # 지금 만드는 DAG


class Node:
    """태스크 하나. >>로 이은 다음 태스크를 기억한다."""

    def __init__(self):
        self.downstream = []
        BUILDING[-1].tasks.append(self)

    def __rshift__(self, other):
        self.downstream.append(other)
        return other


class FakeTask(Node):
    def __init__(self, func):
        super().__init__()
        self.func = func


class FakePod(Node):
    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs


def fake_dag(**settings):
    def wrap(func):
        def build():
            BUILDING.append(FakeDag(settings))
            try:
                func()
            finally:
                built = BUILDING.pop()
            return built
        return build
    return wrap


def fake_task(func):
    return lambda: FakeTask(func)


class Model:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeParam:
    """airflow.sdk.Param: 기본값과 JSON 스키마(type, pattern 등)를 기억한다."""

    def __init__(self, default=None, **schema):
        self.default, self.schema = default, schema


def install_fakes(monkeypatch):
    sdk = types.ModuleType("airflow.sdk")
    sdk.dag, sdk.task, sdk.Param = fake_dag, fake_task, FakeParam
    pod = types.ModuleType("airflow.providers.cncf.kubernetes.operators.pod")
    pod.KubernetesPodOperator = FakePod
    models = types.ModuleType("kubernetes.client.models")
    for name in ("V1Volume", "V1SecretVolumeSource", "V1VolumeMount", "V1ResourceRequirements"):
        setattr(models, name, type(name, (Model,), {}))
    client = types.ModuleType("kubernetes.client")
    client.models = models
    modules = {"airflow": types.ModuleType("airflow"), "airflow.sdk": sdk,
               "airflow.providers.cncf.kubernetes.operators.pod": pod,
               "kubernetes": types.ModuleType("kubernetes"), "kubernetes.client": client,
               "kubernetes.client.models": models}
    for name in ("airflow.providers", "airflow.providers.cncf", "airflow.providers.cncf.kubernetes",
                 "airflow.providers.cncf.kubernetes.operators"):
        modules[name] = types.ModuleType(name)
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def load(monkeypatch, runtime):
    """실행 설정(runtime, None이면 없음)을 넣고 DAG 파일을 새로 읽는다."""
    install_fakes(monkeypatch)
    if runtime is None:
        monkeypatch.delenv("AIRFLOW_GOLD_B_RUNTIME", raising=False)
    else:
        monkeypatch.setenv("AIRFLOW_GOLD_B_RUNTIME", json.dumps(runtime))
    spec = importlib.util.spec_from_file_location("gold_b_dags_under_test", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parts(dag):
    """(설정 확인 태스크, 잡 Pod)"""
    (check,) = [t for t in dag.tasks if isinstance(t, FakeTask)]
    (pod,) = [t for t in dag.tasks if isinstance(t, FakePod)]
    return check, pod


def checks(dags):
    return [parts(d)[0].func for d in (dags.reprocess_dag, dags.compact_dag)]


def job(name):
    pytest.importorskip("pyarrow")
    return importlib.import_module(f"pipelines.gold_b.jobs.{name}")


# ---------- DAG 설정 ----------

def test_reprocess_dag_runs_every_five_minutes_without_airflow_retries(monkeypatch):
    """다시 돌릴지는 잡의 poller가 reprocess_events를 보고 정하므로 Airflow 재시도는 0이다."""
    settings = load(monkeypatch, RUNTIME).reprocess_dag.settings
    assert settings["dag_id"] == "gold_b_reprocess"   # 승인 화면이 기다리는 DAG (agent/approval의 POLLER)
    assert settings["schedule"] == "*/5 * * * *"
    assert (settings["catchup"], settings["is_paused_upon_creation"], settings["max_active_runs"]) == (False, True, 1)
    assert settings["default_args"] == {"retries": 0}
    assert settings["dagrun_timeout"] == timedelta(hours=2)


def test_compact_dag_runs_daily_after_the_day_ends(monkeypatch):
    settings = load(monkeypatch, RUNTIME).compact_dag.settings
    assert settings["dag_id"] == "gold_b_compact"
    assert settings["schedule"] == "30 0 * * *"
    assert (settings["catchup"], settings["is_paused_upon_creation"], settings["max_active_runs"]) == (False, True, 1)
    assert settings["default_args"] == {"retries": 2, "retry_delay": timedelta(minutes=10)}   # 다시 돌려도 결과가 같다


def test_compact_schedule_is_late_enough_for_the_job(monkeypatch, tmp_path):
    """DAG가 날짜 없이 부르는 시각(00:30 UTC)이면 잡이 어제를 '아직 끝나지 않음'(끝 + 10분 전)으로 거부하지 않는다."""
    compact = job("compact")
    minute, hour = map(int, load(monkeypatch, RUNTIME).compact_dag.settings["schedule"].split()[:2])
    logs = []
    code = compact.main([], env={"GOLD_B_LEDGER_ROOT": str(tmp_path)}, log=logs.append,
                        now=lambda: datetime(2026, 10, 24, hour, minute, tzinfo=timezone.utc))
    assert code == 0, logs
    assert logs[0].startswith("파일 합치기 2026-10-23:")   # 어제(UTC)


# ---------- Pod ----------

def test_reprocess_pod_gets_kafka_certificates(monkeypatch):
    check, pod = parts(load(monkeypatch, RUNTIME).reprocess_dag)
    assert check.downstream == [pod]   # 설정 확인이 통과해야 Pod를 띄운다
    k = pod.kwargs
    assert k["cmds"] == ["python3", "-m", "pipelines.gold_b.jobs.reprocess"] and "arguments" not in k
    assert k["name"] == "gold-b-reprocess"
    assert (k["image"], k["namespace"], k["service_account_name"]) == (
        RUNTIME["image"], RUNTIME["namespace"], RUNTIME["service_account"])
    assert (k["in_cluster"], k["automount_service_account_token"], k["on_finish_action"]) == (True, False, "delete_pod")
    assert k["env_vars"]["GOLD_B_LEDGER_ROOT"] == RUNTIME["ledger_root"]
    assert k["env_vars"]["AWS_EC2_METADATA_DISABLED"] == "true"
    (volume,), (mount,) = k["volumes"], k["volume_mounts"]
    assert volume.secret.secret_name == RUNTIME["kafka_tls_secret"]
    assert (mount.name, mount.mount_path, mount.read_only) == (volume.name, "/opt/kafka-tls", True)


def test_reprocess_job_reads_the_pod_kafka_settings(monkeypatch):
    """잡이 Pod 환경변수로 만든 Kafka 설정이 붙인 인증서 파일을 가리킨다."""
    reprocess = job("reprocess")
    env = parts(load(monkeypatch, RUNTIME).reprocess_dag)[1].kwargs["env_vars"]
    assert reprocess.kafka_config_from_env(env) == {
        "bootstrap.servers": RUNTIME["kafka_bootstrap"], "security.protocol": "SSL",
        "ssl.ca.location": "/opt/kafka-tls/ca.crt", "ssl.certificate.location": "/opt/kafka-tls/user.crt",
        "ssl.key.location": "/opt/kafka-tls/user.key"}


def test_compact_pod_needs_only_the_ledger(monkeypatch):
    check, pod = parts(load(monkeypatch, RUNTIME).compact_dag)
    assert check.downstream == [pod]
    k = pod.kwargs
    assert k["cmds"] == ["python3", "-m", "pipelines.gold_b.jobs.compact"]
    assert k["arguments"] == ["--day", "{{ params.day }}"]   # 날짜 입력이 비면 잡이 어제(UTC)를 합친다
    assert k["env_vars"] == {"GOLD_B_LEDGER_ROOT": RUNTIME["ledger_root"], "AWS_EC2_METADATA_DISABLED": "true"}
    assert (k["volumes"], k["volume_mounts"]) == ([], [])   # Kafka를 읽지 않는다
    assert k["automount_service_account_token"] is False


def test_compact_dag_takes_an_optional_day(monkeypatch, tmp_path):
    """손으로 실행할 때 지난 날을 넣을 수 있다 (비우면 어제 UTC, 2026-10-25). Airflow가 형식을 막고, 잡은 빈 값과 날짜를 받는다."""
    compact = job("compact")
    param = load(monkeypatch, RUNTIME).compact_dag.settings["params"]["day"]
    assert (param.default, param.schema["type"]) == ("", "string")
    pattern = re.compile(param.schema["pattern"])
    assert [bool(pattern.search(v)) for v in ("", "2026-10-21", "10/21", "2026-10-21 ")] == [True, True, False, False]
    env, logs = {"GOLD_B_LEDGER_ROOT": str(tmp_path)}, []
    now = lambda: datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)   # noqa: E731
    assert compact.main(["--day", ""], env=env, now=now, log=logs.append) == 0           # 예약 실행: 빈 값 = 어제
    assert compact.main(["--day", "2026-10-21"], env=env, now=now, log=logs.append) == 0
    assert [line.split(":")[0] for line in logs] == ["파일 합치기 2026-10-24", "파일 합치기 2026-10-21"]


def test_both_jobs_share_one_pool(monkeypatch):
    """재처리가 승인 범위 밖 결제 시각 폴더도 고칠 수 있어서 두 잡을 같은 pool에 넣어 같은 시간에 돌지 않게 한다.
    pool을 아직 만들지 않았으면 Airflow 기본 pool이다."""
    dags = load(monkeypatch, RUNTIME)
    assert {parts(d)[1].kwargs["pool"] for d in (dags.reprocess_dag, dags.compact_dag)} == {"gold_b_ledger"}
    dags = load(monkeypatch, {k: v for k, v in RUNTIME.items() if k != "pool"})
    assert {parts(d)[1].kwargs["pool"] for d in (dags.reprocess_dag, dags.compact_dag)} == {"default_pool"}


def test_node_selector_comes_from_runtime(monkeypatch):
    dags = load(monkeypatch, {**RUNTIME, "node_selector": {"karpenter.sh/nodepool": "example-pool"}})
    assert parts(dags.compact_dag)[1].kwargs["node_selector"] == {"karpenter.sh/nodepool": "example-pool"}
    assert parts(load(monkeypatch, RUNTIME).compact_dag)[1].kwargs["node_selector"] == {}


# ---------- 실행 설정 확인 ----------

def test_checks_pass_with_full_runtime(monkeypatch):
    assert [check() for check in checks(load(monkeypatch, RUNTIME))] == [True, True]


def test_dag_file_loads_without_runtime_and_checks_stop(monkeypatch):
    """설정이 없어도 DAG 파일은 읽혀 Airflow에 보이고, 확인 태스크에서 멈춰 Pod를 띄우지 않는다."""
    dags = load(monkeypatch, None)
    for check in checks(dags):
        with pytest.raises(ValueError):
            check()
    assert parts(dags.reprocess_dag)[1].kwargs["image"] == "unconfigured"


@pytest.mark.parametrize("change", [
    {"image": "registry.example/gold-b:latest"},              # digest가 아닌 태그
    {"service_account": ""},
    {"namespace": "agent"}, {"namespace": "kafka"}, {"namespace": "kube-system"},   # 기존 실행 신원 재사용 금지
    {"ledger_root": "/data/gold_b"},                          # 로컬 폴더
    {"ledger_root": "s3://example-bucket"},                   # 원장 폴더가 없음
])
def test_checks_refuse_wrong_runtime(monkeypatch, change):
    for check in checks(load(monkeypatch, {**RUNTIME, **change})):
        with pytest.raises(ValueError):
            check()


def test_reprocess_pod_gets_the_bronze_location_when_set(monkeypatch):
    """bronze_root가 있으면 재처리 Pod에 GOLD_B_BRONZE_ROOT로 준다 (보관 기간이 지난 시간대를 Bronze에서 읽음).
    없으면 주지 않아 잡이 그런 요청을 거부한다. 파일 합치기는 Bronze를 읽지 않는다."""
    name = job("reprocess").ENV_BRONZE_ROOT
    dags = load(monkeypatch, {**RUNTIME, "bronze_root": "s3://example-bucket/bronze_v2"})
    assert parts(dags.reprocess_dag)[1].kwargs["env_vars"][name] == "s3://example-bucket/bronze_v2"
    assert name not in parts(dags.compact_dag)[1].kwargs["env_vars"]
    assert name not in parts(load(monkeypatch, RUNTIME).reprocess_dag)[1].kwargs["env_vars"]


def test_only_reprocess_checks_the_bronze_location(monkeypatch):
    reprocess_check, compact_check = checks(load(monkeypatch, {**RUNTIME, "bronze_root": "/data/bronze_v2"}))
    with pytest.raises(ValueError, match="bronze_root"):
        reprocess_check()
    assert compact_check() is True


def test_only_reprocess_needs_kafka_settings(monkeypatch):
    runtime = {k: v for k, v in RUNTIME.items() if k not in ("kafka_bootstrap", "kafka_tls_secret")}
    reprocess_check, compact_check = checks(load(monkeypatch, runtime))
    with pytest.raises(ValueError, match="kafka_bootstrap"):
        reprocess_check()
    assert compact_check() is True
