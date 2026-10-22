"""Spark cluster mode 제출·최종 완료 확인. 실행 신원은 인프라에서 공급한다."""

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
        uri = get_current_context()["dag_run"].conf.get("config_uri")
        if not isinstance(uri, str) or not re.fullmatch(r"s3://[^/]+/.+\.json", uri):
            raise ValueError("dag_run.conf.config_uri에 고정 Spark 실행 요청 JSON의 S3 경로가 필요합니다")
        if (not re.fullmatch(r".+@sha256:[0-9a-f]{64}", RUNTIME.get("image", ""))
                or not RUNTIME.get("namespace") or not all(RUNTIME.get(k) for k in (
                    "submitter_service_account", "driver_service_account", "executor_service_account"))):
            raise ValueError("AIRFLOW_PIPELINE_RUNTIME에 digest 이미지·namespace·제출기/Driver/Executor 실행 신원을 설정하세요")
        if RUNTIME["namespace"] in {"agent", "kafka", "kube-system"}:
            raise ValueError("기존 agent·Kafka 실행 신원을 재사용하지 마세요")
        return True

    checked = check_request()
    conf = {
        "spark.kubernetes.namespace": RUNTIME.get("namespace", "unconfigured"),
        "spark.kubernetes.container.image": RUNTIME.get("image", "unconfigured"),
        "spark.kubernetes.authenticate.driver.serviceAccountName": RUNTIME.get("driver_service_account", "unconfigured"),
        "spark.kubernetes.authenticate.executor.serviceAccountName": RUNTIME.get("executor_service_account", "unconfigured"),
        "spark.kubernetes.authenticate.submission.oauthTokenFile": "/var/run/secrets/kubernetes.io/serviceaccount/token",
        "spark.kubernetes.authenticate.submission.caCertFile": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        "spark.kubernetes.submission.waitAppCompletion": "true",
        "spark.dynamicAllocation.enabled": "true",
        "spark.dynamicAllocation.shuffleTracking.enabled": "true",
        "spark.dynamicAllocation.minExecutors": "1",
        "spark.dynamicAllocation.initialExecutors": "1",
        "spark.dynamicAllocation.maxExecutors": "2",
        "spark.driver.memory": "1g", "spark.executor.memory": "1g",
        "spark.driver.memoryOverhead": "512m", "spark.executor.memoryOverhead": "512m",
        "spark.kubernetes.driver.request.cores": "0.25",
        "spark.kubernetes.executor.request.cores": "0.6",
        "spark.kubernetes.driver.limit.cores": "1", "spark.kubernetes.executor.limit.cores": "1",
        "spark.executor.cores": "1", "spark.sql.shuffle.partitions": "8",
    }
    # 실제 자원 값은 인프라 공급 설정으로 조정하되 실행 신원·완료 대기는 고정한다.
    overrides = RUNTIME.get("spark_conf", {})
    protected = {key for key in conf if "authenticate" in key or key in {
        "spark.kubernetes.namespace", "spark.kubernetes.container.image", "spark.kubernetes.submission.waitAppCompletion"}}
    if set(overrides) & protected:
        raise ValueError("실행 신원·이미지·완료 확인은 전용 설정 필드로 지정하세요")
    conf.update(overrides)
    for key, value in RUNTIME.get("node_selector", {}).items():
        conf["spark.kubernetes.node.selector." + key] = value
    arguments = ["--master", RUNTIME.get("master", "k8s://https://kubernetes.default.svc"),
                 "--deploy-mode", "cluster"]
    for key, value in conf.items():
        arguments.extend(["--conf", key + "=" + str(value)])
    arguments.extend(["local:///opt/pipelines/pipelines/spark_batch.py", "--config-uri", "{{ dag_run.conf['config_uri'] }}"])
    worker = KubernetesPodOperator(
        task_id="submit_spark",
        name="silver-gold-a-submit",
        namespace=RUNTIME.get("namespace", "unconfigured"),
        service_account_name=RUNTIME.get("submitter_service_account", "unconfigured"),
        image=RUNTIME.get("image", "unconfigured"),
        in_cluster=True,
        automount_service_account_token=True,
        cmds=["/opt/spark/bin/spark-submit"],
        arguments=arguments,
        node_selector=RUNTIME.get("node_selector", {}),
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": "256Mi", "ephemeral-storage": "256Mi"},
            limits={"cpu": "500m", "memory": "768Mi", "ephemeral-storage": "1Gi"},
        ),
        get_logs=True,
        log_pod_spec_on_failure=False,
        do_xcom_push=False,
        on_finish_action="delete_pod",
        startup_timeout_seconds=300,
    )
    checked >> worker


batch_dag = silver_gold_a_batch()
