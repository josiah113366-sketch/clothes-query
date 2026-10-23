"""조사 DAG: 5분마다 조사 이미지를 Pod로 한 번 실행한다 (아직 조사하지 않은 이상을 최대 N건 조사해 리포트를 쓴다).

코드는 이미지 안의 run_investigation.py가 한다. 이 파일은 실행만 연결한다. 새 DAG는 처음에 paused로 등록된다.
판정 DAG와 따로 두는 이유: 조사가 오래 걸려도 판정 순찰이 밀리지 않게 하려는 것이다.
"""
from datetime import UTC, datetime

from agent_common import DAG_RUN_TIMEOUT, load_config, pod_kwargs
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag
from kubernetes.client import models as k8s

CONFIG = load_config()


@dag(
    dag_id="agent_investigation_5min",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    dagrun_timeout=DAG_RUN_TIMEOUT,
    tags=["agent", "investigation"],
)
def agent_investigation():
    kwargs = pod_kwargs(CONFIG, "investigation")
    kwargs["container_resources"] = k8s.V1ResourceRequirements(**kwargs.pop("resources"))
    KubernetesPodOperator(**kwargs)


agent_investigation()
