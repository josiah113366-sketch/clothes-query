"""업무 실행용 수동 DAG. 이미지·실행 신원은 인프라 설정으로 공급한다."""

import json
import os
import re
from datetime import UTC, datetime, timedelta

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, get_current_context, task
from kubernetes.client import models as k8s

RUNTIME = json.loads(os.environ.get("AIRFLOW_PIPELINE_RUNTIME", "{}"))


@dag(
    dag_id="silver_gold_a_batch",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={"retries": 0},
    tags=["pipelines", "manual"],
)
def silver_gold_a_batch():
    @task
    def check_request():
        batch = get_current_context()["dag_run"].conf.get("batch")
        if not isinstance(batch, dict) or batch.get("job") not in {"trade", "reviews", "funnels", "members"}:
            raise ValueError("dag_run.conf.batch에 작업별 JSON 입력이 필요합니다")
        if (not re.fullmatch(r".+@sha256:[0-9a-f]{64}", RUNTIME.get("image", ""))
                or not RUNTIME.get("namespace") or not RUNTIME.get("service_account")):
            raise ValueError("AIRFLOW_PIPELINE_RUNTIME에 digest 이미지·namespace·service_account를 설정하세요")
        if RUNTIME["namespace"] in {"agent", "kafka", "kube-system"}:
            raise ValueError("기존 agent·Kafka 실행 신원을 재사용하지 마세요")
        return True

    checked = check_request()
    worker = KubernetesPodOperator(
        task_id="run_batch",
        name="silver-gold-a-batch",
        namespace=RUNTIME.get("namespace", "unconfigured"),
        service_account_name=RUNTIME.get("service_account", "unconfigured"),
        image=RUNTIME.get("image", "unconfigured"),
        in_cluster=True,
        automount_service_account_token=False,
        cmds=["python", "-m", "pipelines.batch"],
        env_vars={"BATCH_CONFIG": "{{ dag_run.conf['batch'] | tojson }}"},
        node_selector=RUNTIME.get("node_selector", {}),
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": "256Mi", "ephemeral-storage": "512Mi"},
            limits={"cpu": "1", "memory": "1Gi", "ephemeral-storage": "3Gi"},
        ),
        get_logs=True,
        log_pod_spec_on_failure=False,
        do_xcom_push=False,
        on_finish_action="delete_pod",
        startup_timeout_seconds=300,
    )
    checked >> worker


batch_dag = silver_gold_a_batch()
