"""Gold B 재처리·파일 합치기. 잡은 Gold B 이미지(pipelines/gold_b/Dockerfile)에서 파이썬으로 돈다 (Spark 아님).

- gold_b_reprocess: 5분마다 승인된 재처리 요청 하나를 골라 돌린다. 승인 화면이 이 DAG를 기다린다 (agent/approval의 POLLER).
  Kafka 보관 기간(7일)이 지난 시간대는 Bronze v2에서 읽는다 (bronze_root를 설정했을 때만, 없으면 그런 요청은 거부).
- gold_b_compact: 매일 00:30 UTC에 끝난 어제(UTC) 시간 폴더의 작은 파일을 합친다.
  손으로 실행할 때 날짜 입력(day, YYYY-MM-DD)을 넣으면 그 날을 합친다 (비우면 어제. 2026-10-25).
  날짜는 Pod 환경변수 GOLD_B_COMPACT_DAY로 넘긴다. 이 값을 모르는 옛 이미지는 무시하고 어제를 합친다 (실패하지 않음).
두 DAG는 같은 pool에 넣어 같은 시간에 돌지 않는다 (재처리가 승인 범위 밖 결제 시각 폴더도 고칠 수 있음).
실행 신원·이미지·주소는 인프라가 AIRFLOW_GOLD_B_RUNTIME JSON으로 공급한다. 없으면 확인 태스크에서 멈추고 Pod를 띄우지 않는다.
잡 설명은 pipelines/gold_b/jobs/README.md, 설계는 docs/design/gold-b/README.md 「재실행·재처리 설계와 검증」.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import Param, dag, task
from kubernetes.client import models as k8s

RUNTIME = json.loads(os.environ.get("AIRFLOW_GOLD_B_RUNTIME", "{}"))
# 슬롯 1개짜리 pool을 인프라가 만들면 그 이름 (예: gold_b_ledger). 아직 없으면 기본 pool (지금 Airflow는 동시 작업 1개)
POOL = RUNTIME.get("pool") or "default_pool"
KAFKA_TLS_DIR = "/opt/kafka-tls"   # Secret 키: ca.crt(Kafka 클러스터 CA), user.crt, user.key


def check_runtime(reprocess):
    """실행 설정 확인. 틀리면 ValueError로 멈추고 Pod를 띄우지 않는다. Kafka·Bronze 설정은 재처리만 쓴다."""
    if (not re.fullmatch(r".+@sha256:[0-9a-f]{64}", RUNTIME.get("image", ""))
            or not RUNTIME.get("namespace") or not RUNTIME.get("service_account")):
        raise ValueError("AIRFLOW_GOLD_B_RUNTIME에 digest 이미지·namespace·실행 신원(service_account)을 설정하세요")
    if RUNTIME["namespace"] in {"agent", "kafka", "kube-system"}:
        raise ValueError("기존 agent·Kafka 실행 신원을 재사용하지 마세요")
    if not re.fullmatch(r"s3://[^/]+/.+", RUNTIME.get("ledger_root", "")):
        raise ValueError("ledger_root에 원장 위치(s3://<버킷>/gold_b)를 설정하세요")
    if reprocess and not (RUNTIME.get("kafka_bootstrap") and RUNTIME.get("kafka_tls_secret")):
        raise ValueError("재처리는 Kafka 주소(kafka_bootstrap)와 인증서 Secret(kafka_tls_secret)이 필요합니다")
    if reprocess and RUNTIME.get("bronze_root") and not re.fullmatch(r"s3://[^/]+/.+", RUNTIME["bronze_root"]):
        raise ValueError("bronze_root에는 Bronze v2 위치(s3://<버킷>/bronze_v2)를 설정하세요")
    return True


def gold_b_pod(task_id, module, reprocess, extra_env=None):
    """Gold B 잡 하나를 돌리는 Pod. 재처리면 Kafka 인증서를 붙이고 KAFKA_*·Bronze 위치 환경변수를 준다.
    extra_env는 더 줄 환경변수다 (값에 Airflow 템플릿을 쓸 수 있음, 예: 합치기의 날짜 입력)."""
    env = {"GOLD_B_LEDGER_ROOT": RUNTIME.get("ledger_root", "unconfigured"), "AWS_EC2_METADATA_DISABLED": "true",
           **(extra_env or {})}
    volumes, mounts = [], []
    if reprocess and RUNTIME.get("bronze_root"):
        env["GOLD_B_BRONZE_ROOT"] = RUNTIME["bronze_root"]
    if reprocess:
        env.update({"KAFKA_BOOTSTRAP": RUNTIME.get("kafka_bootstrap", "unconfigured"),
                    "KAFKA_SECURITY_PROTOCOL": "SSL",
                    "KAFKA_SSL_CA_FILE": KAFKA_TLS_DIR + "/ca.crt",
                    "KAFKA_SSL_CERT_FILE": KAFKA_TLS_DIR + "/user.crt",
                    "KAFKA_SSL_KEY_FILE": KAFKA_TLS_DIR + "/user.key"})
        volumes = [k8s.V1Volume(name="kafka-tls", secret=k8s.V1SecretVolumeSource(
            secret_name=RUNTIME.get("kafka_tls_secret", "unconfigured")))]
        mounts = [k8s.V1VolumeMount(name="kafka-tls", mount_path=KAFKA_TLS_DIR, read_only=True)]
    return KubernetesPodOperator(
        task_id=task_id,
        name="gold-b-" + task_id,
        namespace=RUNTIME.get("namespace", "unconfigured"),
        service_account_name=RUNTIME.get("service_account", "unconfigured"),
        image=RUNTIME.get("image", "unconfigured"),
        in_cluster=True,
        automount_service_account_token=False,
        cmds=["python3", "-m", module],
        env_vars=env,
        node_selector=RUNTIME.get("node_selector", {}),
        tolerations=[{"key": "clothes-query/dedicated", "operator": "Equal", "value": "spark", "effect": "NoSchedule"}]
        if RUNTIME.get("node_selector", {}).get("karpenter.sh/nodepool") == "clothes-query-dev-compute-spark" else [],
        labels={"app": "gold-b-ledger-jobs"},
        volumes=volumes,
        volume_mounts=mounts,
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "250m", "memory": "512Mi", "ephemeral-storage": "256Mi"},
            limits={"cpu": "1", "memory": "2Gi", "ephemeral-storage": "1Gi"},
        ),
        pool=POOL,
        get_logs=True,
        log_pod_spec_on_failure=False,
        do_xcom_push=False,
        on_finish_action="delete_pod",
        startup_timeout_seconds=300,
    )


@dag(
    dag_id="gold_b_reprocess",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(hours=2),
    default_args={"retries": 0},   # 다시 돌릴지는 잡의 poller가 reprocess_events를 보고 정한다
    tags=["pipelines", "gold_b"],
)
def gold_b_reprocess():
    @task
    def check_reprocess_runtime():
        return check_runtime(reprocess=True)

    check_reprocess_runtime() >> gold_b_pod("reprocess", "pipelines.gold_b.jobs.reprocess", reprocess=True)


@dag(
    dag_id="gold_b_compact",
    schedule="30 0 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},   # 합치기는 다시 돌려도 결과가 같다
    # 손으로 실행할 때 지난 날을 합칠 수 있게 한다 (예: 적재 잡이 Kafka를 따라잡으며 쌓은 날). 예약 실행은 빈 값 = 어제
    params={"day": Param("", type="string", pattern=r"^(\d{4}-\d{2}-\d{2})?$",
                         description="합칠 날 (UTC, YYYY-MM-DD). 비우면 어제(UTC). 끝나지 않은 날은 잡이 거부한다")},
    tags=["pipelines", "gold_b"],
)
def gold_b_compact():
    @task
    def check_compact_runtime():
        return check_runtime(reprocess=False)

    # 날짜 입력이 비면 잡이 어제(UTC)를 합친다. 명령 인자가 아니라 환경변수라 옛 이미지에서도 실패하지 않는다
    check_compact_runtime() >> gold_b_pod("compact", "pipelines.gold_b.jobs.compact", reprocess=False,
                                          extra_env={"GOLD_B_COMPACT_DAY": "{{ params.day }}"})


reprocess_dag = gold_b_reprocess()
compact_dag = gold_b_compact()
