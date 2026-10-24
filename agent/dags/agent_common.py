"""판정·조사 DAG가 같이 쓰는 설정 읽기와 Pod 설정 만들기. Airflow를 불러오지 않아서 일반 파이썬으로 시험할 수 있다.

실제 환경 값(이미지 주소, workgroup, 리전, 모델 ID)은 Git에 넣지 않고, 인프라 담당이 업무용 ConfigMap으로 공급하는
JSON 환경 변수 AIRFLOW_AGENT_CONFIG로 받는다(확인용 DAG infra_probe가 AIRFLOW_INFRA_PROBE_CONFIG로 받는 것과 같은 방식).
ConfigMap은 비밀 저장소가 아니다. 비밀번호·토큰은 이 설정에 넣지 않는다(AWS 권한은 Pod의 ServiceAccount가 준다).
"""
import json
import os
from datetime import timedelta

CONFIG_ENV = "AIRFLOW_AGENT_CONFIG"
NAMESPACE = "agent"
REQUIRED = ("detect_image", "investigate_image", "detect_workgroup", "investigate_workgroup", "region", "bedrock_model_id")
DEFAULT_INVESTIGATE_MAX = 3
# 판정 Pod에 선택으로 넘기는 R6 설정: (설정 JSON 키, Pod 환경 변수 이름). agent/detect/run_job.py가 읽는다
R6_KEYS = (("silver_checks_table", "SILVER_CHECKS_TABLE"), ("silver_runs_table", "SILVER_RUNS_TABLE"), ("r6_check_name", "R6_CHECK_NAME"))

# 임의 값(측정 전). 실제 실행 시간과 자원 사용량을 재영 님과 함께 확인한 뒤 조정한다
RESOURCES = {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "500m", "memory": "1Gi"}}
DETECT_TIMEOUT = timedelta(minutes=3)
INVESTIGATE_TIMEOUT = timedelta(minutes=4)
DAG_RUN_TIMEOUT = timedelta(minutes=5)   # 5분 주기보다 길게 두지 않는다(다음 회차가 밀리지 않게)

# Airflow가 Pod를 만들 때 풀어 주는 값. 판정 순찰 번호가 이 시각으로 정해져서 실패 작업을 다시 돌려도 같은 번호가 된다
TICK_TEMPLATE = "{{ (data_interval_end or dag_run.run_after).strftime('%Y-%m-%dT%H:%M:%SZ') }}"


def load_config(env=None):
    """환경 변수의 JSON을 읽어 검사한다. 빠진 키는 이름을 모두 적어 오류로 알린다."""
    env = os.environ if env is None else env
    raw = env.get(CONFIG_ENV)
    if not raw:
        raise RuntimeError(f"환경 변수 {CONFIG_ENV}가 없습니다. 인프라 담당이 업무용 ConfigMap으로 공급해야 합니다.")
    try:
        config = json.loads(raw)
    except ValueError as error:
        raise RuntimeError(f"{CONFIG_ENV}가 JSON이 아닙니다: {error.msg}") from None
    if not isinstance(config, dict):
        raise RuntimeError(f"{CONFIG_ENV}는 JSON 객체여야 합니다.")
    missing = [k for k in REQUIRED if not str(config.get(k, "")).strip()]
    if missing:
        raise RuntimeError(f"{CONFIG_ENV}에 필요한 키가 없습니다: {', '.join(missing)}")
    config = {k: (v.strip() if isinstance(v, str) else v) for k, v in config.items()}
    config["investigate_max"] = int(config.get("investigate_max") or DEFAULT_INVESTIGATE_MAX)
    if config["investigate_max"] < 1:
        raise RuntimeError("investigate_max는 1 이상이어야 합니다.")
    return config


def pod_kwargs(config, role):
    """KubernetesPodOperator에 넘길 값. role: 'detection' | 'investigation'. 컨테이너 실행 명령은 이미지의 ENTRYPOINT를 그대로 쓴다."""
    if role not in ("detection", "investigation"):
        raise ValueError(f"알 수 없는 역할: {role}")
    env_vars = {"AWS_REGION": config["region"], "AWS_EC2_METADATA_DISABLED": "true"}   # Pod Identity를 쓰므로 EC2 메타데이터 조회는 끈다
    if role == "detection":
        env_vars.update({"ATHENA_WORKGROUP": config["detect_workgroup"], "JUDGE_TICK": TICK_TEMPLATE})
        for key, name in R6_KEYS:      # R6(Silver 주문 총액 검사) 설정: 설정 JSON에 있을 때만 판정 Pod에 전달한다. 없으면 R6은 돌지 않는다
            if str(config.get(key, "")).strip():
                env_vars[name] = str(config[key]).strip()
        image, service_account, timeout = config["detect_image"], "detection-job", DETECT_TIMEOUT
    else:
        env_vars.update({"ATHENA_WORKGROUP": config["investigate_workgroup"], "BEDROCK_MODEL_ID": config["bedrock_model_id"],
                         "INVESTIGATE_MAX": str(config["investigate_max"])})
        image, service_account, timeout = config["investigate_image"], "investigation-agent", INVESTIGATE_TIMEOUT
    kwargs = {"task_id": role, "name": f"agent-{role}", "namespace": NAMESPACE, "in_cluster": True,
              "service_account_name": service_account, "automount_service_account_token": False, "image": image,
              "env_vars": env_vars, "resources": RESOURCES, "get_logs": True, "on_finish_action": "delete_pod",
              "do_xcom_push": False, "startup_timeout_seconds": 180, "execution_timeout": timeout,
              "retries": 1, "retry_delay": timedelta(seconds=30)}
    if config.get("hostname"):                                 # 새 노드가 생기지 않게 기존 노드에 고정하고 싶을 때만(확인용 DAG와 같은 선택 키)
        kwargs["node_selector"] = {"kubernetes.io/hostname": config["hostname"]}
    return kwargs
