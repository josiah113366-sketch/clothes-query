"""판정 잡 DAG: 5분마다 판정 이미지를 Pod로 한 번 실행한다 (규칙 R1·R3~R6 판정, 재처리 뒤 재판정).

코드는 이미지 안의 run_job.py가 한다. 이 파일은 실행만 연결한다. 새 DAG는 처음에 paused로 등록된다.
"""
from datetime import UTC, datetime

from agent_common import DAG_RUN_TIMEOUT, load_config, pod_kwargs
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag
from kubernetes.client import models as k8s

CONFIG = load_config()


@dag(
    dag_id="agent_detection_5min",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,                  # 밀린 회차를 한꺼번에 돌리지 않는다. 순찰 번호가 시각으로 정해지므로 안 돈 회차는 다음 순찰에서 보완한다
    max_active_runs=1,
    is_paused_upon_creation=True,
    dagrun_timeout=DAG_RUN_TIMEOUT,
    tags=["agent", "detection"],
)
def agent_detection():
    kwargs = pod_kwargs(CONFIG, "detection")
    kwargs["container_resources"] = k8s.V1ResourceRequirements(**kwargs.pop("resources"))
    KubernetesPodOperator(**kwargs)


agent_detection()
