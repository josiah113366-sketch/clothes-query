"""Spark cluster mode 제출·최종 완료 확인. 실행 신원은 인프라에서 공급한다."""

import json
import os
import re
from datetime import UTC, datetime, timedelta

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, get_current_context, task
from kubernetes.client import models as k8s

RUNTIME = json.loads(os.environ.get("AIRFLOW_PIPELINE_RUNTIME", "{}"))
NODE_SELECTOR = RUNTIME.get("node_selector", {"karpenter.sh/nodepool": "clothes-query-dev-compute-spark"})
TEMPLATE_DIR = "/opt/spark/infra"


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
        if not re.fullmatch(r"[a-z][a-z0-9_]*", RUNTIME.get("silver_database", "")):
            raise ValueError("AIRFLOW_PIPELINE_RUNTIME.silver_database에 배포된 R6 Glue DB를 지정하세요")
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
        "spark.kubernetes.driver.podTemplateFile": TEMPLATE_DIR + "/driver-pod-template.yaml",
        "spark.kubernetes.executor.podTemplateFile": TEMPLATE_DIR + "/executor-pod-template.yaml",
        "spark.kubernetes.driver.podTemplateContainerName": "spark-main",
        "spark.kubernetes.executor.podTemplateContainerName": "spark-main",
        "spark.dynamicAllocation.enabled": "true",
        "spark.dynamicAllocation.shuffleTracking.enabled": "true",
        "spark.dynamicAllocation.minExecutors": "1",
        "spark.dynamicAllocation.initialExecutors": "1",
        "spark.dynamicAllocation.maxExecutors": "2",
        # infra/platform/spark/runtime.py의 dedicated 자원 프로필을 따른다.
        "spark.driver.memory": "512m", "spark.executor.memory": "1g",
        "spark.driver.memoryOverhead": "512m", "spark.executor.memoryOverhead": "512m",
        "spark.kubernetes.driver.request.cores": "250m",
        "spark.kubernetes.executor.request.cores": "500m",
        "spark.kubernetes.driver.limit.cores": "1", "spark.kubernetes.executor.limit.cores": "1",
        "spark.driver.cores": "1", "spark.executor.cores": "1", "spark.sql.shuffle.partitions": "4",
    }
    # 실제 자원 값은 인프라 공급 설정으로 조정하되 실행 신원·완료 대기는 고정한다.
    overrides = RUNTIME.get("spark_conf", {})
    protected = {key for key in conf if "authenticate" in key or "podTemplate" in key or key in {
        "spark.kubernetes.namespace", "spark.kubernetes.container.image", "spark.kubernetes.submission.waitAppCompletion"}}
    protected.add("spark.kubernetes.driver.pod.name")
    if set(overrides) & protected:
        raise ValueError("실행 신원·이미지·완료 확인은 전용 설정 필드로 지정하세요")
    conf.update(overrides)
    for key, value in NODE_SELECTOR.items():
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
        cmds=["python3", "-m", "pipelines.submit_spark"],
        arguments=["--namespace", RUNTIME.get("namespace", "unconfigured"),
                   "--template-dir", TEMPLATE_DIR, "--timeout-seconds", "3000", "--", *arguments],
        env_vars={"SPARK_DRIVER_MEMORY": "512m"},
        node_selector=NODE_SELECTOR,
        tolerations=[k8s.V1Toleration(key="clothes-query/dedicated", operator="Equal",
                                    value="spark", effect="NoSchedule")],
        volumes=[k8s.V1Volume(name="spark-runtime", config_map=k8s.V1ConfigMapVolumeSource(
            name=RUNTIME.get("runtime_configmap", "silver-gold-a-runtime")))],
        volume_mounts=[k8s.V1VolumeMount(name="spark-runtime", mount_path=TEMPLATE_DIR, read_only=True)],
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "250m", "memory": "512Mi", "ephemeral-storage": "256Mi"},
            limits={"cpu": "500m", "memory": "1Gi", "ephemeral-storage": "1Gi"},
        ),
        get_logs=True,
        log_pod_spec_on_failure=False,
        do_xcom_push=False,
        on_finish_action="delete_pod",
        startup_timeout_seconds=300,
    )
    checked >> worker
    publish = KubernetesPodOperator(
        task_id="publish_r6",
        name="silver-r6-publish",
        namespace=RUNTIME.get("namespace", "unconfigured"),
        service_account_name=RUNTIME.get("driver_service_account", "unconfigured"),
        image=RUNTIME.get("image", "unconfigured"),
        in_cluster=True,
        cmds=["python3", "-m", "pipelines.r6_publication"],
        arguments=["--config-uri", "{{ dag_run.conf['config_uri'] }}",
                   "--database", RUNTIME.get("silver_database", "unconfigured")],
        # Gold A가 실패해도 완료된 Silver 품질 결과는 제공한다. 최종 실패는 아래 watcher가 유지한다.
        trigger_rule="all_done",
        node_selector=NODE_SELECTOR,
        tolerations=[k8s.V1Toleration(key="clothes-query/dedicated", operator="Equal",
                                    value="spark", effect="NoSchedule")],
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "250m", "memory": "512Mi"},
            limits={"cpu": "500m", "memory": "1Gi"},
        ),
        get_logs=True,
        log_pod_spec_on_failure=False,
        do_xcom_push=False,
        on_finish_action="delete_pod",
        startup_timeout_seconds=300,
    )
    worker >> publish

    @task(trigger_rule="one_failed", retries=0)
    def report_failure():
        # all_done 공개 태스크가 성공해도 상위 Spark 실패를 DAG 성공으로 숨기지 않는다.
        raise RuntimeError("요청 검사·Spark 처리·R6 공개 중 실패가 있습니다")

    failed = report_failure()
    checked >> failed
    worker >> failed
    publish >> failed


batch_dag = silver_gold_a_batch()
