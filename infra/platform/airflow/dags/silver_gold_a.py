"""Spark cluster mode 제출·최종 완료 확인. 실행 신원은 인프라에서 공급한다."""

import json
import os
import re
from datetime import UTC, datetime, timedelta

from airflow.providers.cncf.kubernetes.callbacks import KubernetesPodOperatorCallback
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import dag, get_current_context, task
from kubernetes.client import models as k8s

RUNTIME = json.loads(os.environ.get("AIRFLOW_PIPELINE_RUNTIME", "{}"))
NODE_SELECTOR = RUNTIME.get("node_selector", {"karpenter.sh/nodepool": "clothes-query-dev-compute-spark"})
TEMPLATE_DIR = "/opt/spark/infra"


class FunnelContinuationCallback(KubernetesPodOperatorCallback):
    """Small termination message -> explicit XCom, without a pods/exec sidecar."""
    @staticmethod
    def on_pod_completion(*, pod, client, mode, operator, context, **kwargs):
        statuses = (pod.status.container_statuses or []) if pod and pod.status else []
        terminated = next((status.state.terminated for status in statuses
                           if status.name == operator.base_container_name and status.state and status.state.terminated), None)
        if not terminated or terminated.exit_code != 0 or not terminated.message or len(terminated.message) > 3500:
            raise ValueError("다음 퍼널 묶음의 정상 종료 메시지가 없습니다")
        value = json.loads(terminated.message)
        if set(value) != {"continue", "config_uri", "next_run_id"} or type(value["continue"]) is not bool:
            raise ValueError("퍼널 연속 실행 응답이 다릅니다")
        if value["continue"] and (not re.fullmatch(r"s3://[^/]+/.+\.json", value["config_uri"])
                                  or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value["next_run_id"])):
            raise ValueError("다음 퍼널 실행 요청 주소·ID가 다릅니다")
        context["ti"].xcom_push(key="funnel_continuation", value=value)


def build_dag(channel):
    return dag(
    dag_id="silver_gold_a_" + channel,
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={"retries": 0},
    tags=["pipelines", "manual"],
    )(lambda: silver_gold_a_batch(channel))()


def silver_gold_a_batch(channel):
    reprocess = channel == "reprocess"
    job = "trade" if reprocess else channel
    reprocess_runtime = RUNTIME.get("reprocess", {})
    config_uri = (reprocess_runtime.get("output_root", "unconfigured").rstrip("/") +
                  "/pipelines/requests/reprocess/{{ dag_run.conf['request_id'] }}-{{ dag_run.conf.get('attempt', 1) }}.json"
                  if reprocess else "{{ dag_run.conf['config_uri'] }}")
    @task
    def check_request():
        request = get_current_context()["dag_run"].conf
        if request.get("mode", "full") not in {"full", "demo", "incremental"} or (request.get("mode") in {"demo", "incremental"} and channel != "funnels"):
            raise ValueError("demo·incremental 모드는 퍼널 DAG에서만 사용할 수 있습니다")
        if request.get("mode") == "incremental" and (not RUNTIME.get("funnel_athena_workgroup")
                or not RUNTIME.get("funnel_athena_output", "").startswith("s3://")):
            raise ValueError("증분 실행의 Athena 조회 검증 설정이 필요합니다")
        if reprocess:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request.get("request_id", "")) or not reprocess_runtime:
                raise ValueError("재처리 승인 요청과 reprocess 실행 설정이 필요합니다")
        else:
            uri = request.get("config_uri")
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
        if not re.fullmatch(r"[a-z][a-z0-9_]*", RUNTIME.get("gold_database", "")):
            raise ValueError("AIRFLOW_PIPELINE_RUNTIME.gold_database에 배포된 Gold A Glue DB를 지정하세요")
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
    entry = ("local:///opt/pipelines/pipelines/{{ 'funnel_demo.py' if dag_run.conf.get('mode') == 'demo' else 'funnel_incremental.py' if dag_run.conf.get('mode') == 'incremental' else 'spark_batch.py' }}"
             if channel == "funnels" else "local:///opt/pipelines/pipelines/spark_batch.py")
    arguments.extend([entry, "--config-uri", config_uri,
                      "--expected-job", job])
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
    def python_pod(task_id, module, arguments, trigger="all_success", callbacks=None):
        return KubernetesPodOperator(
        task_id=task_id,
        name="silver-gold-a-" + task_id.replace("_", "-"),
        namespace=RUNTIME.get("namespace", "unconfigured"),
        service_account_name=RUNTIME.get("driver_service_account", "unconfigured"),
        image=RUNTIME.get("image", "unconfigured"),
        in_cluster=True,
        cmds=["python3", "-m", module],
        arguments=arguments,
        # Gold A가 실패해도 완료된 Silver 품질 결과는 제공한다. 최종 실패는 아래 watcher가 유지한다.
        trigger_rule=trigger,
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
        callbacks=callbacks,
    )
    all_tasks = [checked, worker]
    if reprocess:
        prepared = python_pod("prepare_input_manifest", "pipelines.reprocess", ["prepare",
            "--request-json", "{{ dag_run.conf | tojson }}", "--runtime-json", json.dumps(reprocess_runtime)])
        checked >> prepared >> worker
        all_tasks.append(prepared)
    if job != "reviews":
        publish = python_pod("publish_r6", "pipelines.r6_publication", ["--config-uri", config_uri,
            "--database", RUNTIME.get("silver_database", "unconfigured")], "all_done")
        worker >> publish
        all_tasks.append(publish)
    gold = python_pod("publish_gold", "pipelines.gold_publication", ["--config-uri", config_uri,
        "--database", RUNTIME.get("gold_database", "unconfigured"),
        "--athena-workgroup", RUNTIME.get("funnel_athena_workgroup", ""),
        "--athena-output", RUNTIME.get("funnel_athena_output", "")])
    worker >> gold
    all_tasks.append(gold)
    if channel == "funnels":
        next_batch = python_pod("prepare_next_funnel_batch", "pipelines.funnel_control", ["--config-uri", config_uri],
                                callbacks=[FunnelContinuationCallback])
        gold >> next_batch

        @task.branch
        def choose_funnel_continuation():
            context = get_current_context()
            value = context["ti"].xcom_pull(task_ids="prepare_next_funnel_batch", key="funnel_continuation") or {}
            return "trigger_next_funnel_batch" if value.get("continue") else "funnel_inventory_complete"

        @task
        def funnel_inventory_complete():
            return "captured inventory complete; future input discovery remains manual"

        choice = choose_funnel_continuation()
        trigger_next = TriggerDagRunOperator(task_id="trigger_next_funnel_batch", trigger_dag_id="silver_gold_a_funnels",
            trigger_run_id="{{ ti.xcom_pull(task_ids='prepare_next_funnel_batch', key='funnel_continuation')['next_run_id'] }}",
            conf={"mode": "incremental", "config_uri": "{{ ti.xcom_pull(task_ids='prepare_next_funnel_batch', key='funnel_continuation')['config_uri'] }}"},
            wait_for_completion=False, skip_when_already_exists=True)
        next_batch >> choice
        choice >> trigger_next
        choice >> funnel_inventory_complete()
        all_tasks.extend([next_batch, choice, trigger_next])
    if reprocess:
        finished = python_pod("record_reprocess_result", "pipelines.reprocess", ["finish",
            "--request-json", "{{ dag_run.conf | tojson }}", "--runtime-json", json.dumps(reprocess_runtime)], "all_done")
        gold >> finished
        publish >> finished
        all_tasks.append(finished)

    @task(trigger_rule="one_failed", retries=0)
    def report_failure():
        # all_done 공개 태스크가 성공해도 상위 Spark 실패를 DAG 성공으로 숨기지 않는다.
        raise RuntimeError("요청 검사·Spark 처리·R6 공개 중 실패가 있습니다")

    failed = report_failure()
    for task_node in all_tasks:
        task_node >> failed


trade_dag = build_dag("trade")
funnels_dag = build_dag("funnels")
reviews_dag = build_dag("reviews")
reprocess_dag = build_dag("reprocess")
