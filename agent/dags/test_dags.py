"""판정·조사 DAG의 설정 읽기와 Pod 설정을 시험한다. Airflow 없이 돈다(표준 라이브러리만 사용).

실행: python3 test_dags.py
Airflow가 설치된 환경(예: 개발자 PC의 venv)에서는 --airflow를 붙이면 실제 DAG 파일도 불러와 본다.
"""
import ast
import json
import sys
from datetime import timedelta
from pathlib import Path

from agent_common import CONFIG_ENV, DEFAULT_INVESTIGATE_MAX, R6_KEYS, REQUIRED, RESOURCES, TICK_TEMPLATE, load_config, pod_kwargs

ok = True
HERE = Path(__file__).resolve().parent


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


def raises(fn):
    try:
        fn()
    except RuntimeError as error:
        return str(error)
    return None


GOOD = {"detect_image": "registry.example/detect@sha256:aaa", "investigate_image": "registry.example/investigate@sha256:bbb",
        "detect_workgroup": "wg-detect", "investigate_workgroup": "wg-investigate", "region": "ap-northeast-1",
        "bedrock_model_id": "jp.anthropic.claude-haiku-4-5-20251001-v1:0"}


def env(**over):
    return {CONFIG_ENV: json.dumps({**GOOD, **over})}


# --- 설정 읽기 ---
cfg = load_config(env())
check("설정: 필요한 키가 모두 있으면 읽힘, 조사 최대 건수 기본 3", (cfg["detect_workgroup"], cfg["investigate_max"]), ("wg-detect", DEFAULT_INVESTIGATE_MAX))
check("설정: investigate_max를 주면 그 값(문자여도 정수로)", load_config(env(investigate_max="5"))["investigate_max"], 5)
check("설정: 환경 변수가 없으면 이름을 알려 주며 실패", CONFIG_ENV in (raises(lambda: load_config({})) or ""), True)
check("설정: JSON이 아니면 실패", "JSON이 아닙니다" in (raises(lambda: load_config({CONFIG_ENV: "{x"})) or ""), True)
check("설정: JSON 객체가 아니면(목록) 실패", "객체" in (raises(lambda: load_config({CONFIG_ENV: "[1]"})) or ""), True)
missing = raises(lambda: load_config({CONFIG_ENV: json.dumps({k: v for k, v in GOOD.items() if k not in ("region", "bedrock_model_id")})}))
check("설정: 빠진 키를 모두 적어 실패", ("region" in missing, "bedrock_model_id" in missing, "detect_image" in missing), (True, True, False))
check("설정: 빈 문자열·공백만 있어도 빠진 것으로 봄", "region" in (raises(lambda: load_config(env(region="  "))) or ""), True)
check("설정: investigate_max가 0이면 비어 있는 값으로 보아 기본 3", load_config(env(investigate_max=0))["investigate_max"], DEFAULT_INVESTIGATE_MAX)
check("설정: investigate_max가 음수이면 실패", "1 이상" in (raises(lambda: load_config(env(investigate_max=-2))) or ""), True)
check("설정: 값 앞뒤 공백은 지움", load_config(env(region=" ap-northeast-1 "))["region"], "ap-northeast-1")
check("설정: 필요한 키 목록", REQUIRED, ("detect_image", "investigate_image", "detect_workgroup", "investigate_workgroup", "region", "bedrock_model_id"))

# --- Pod 설정 ---
d, i = pod_kwargs(cfg, "detection"), pod_kwargs(cfg, "investigation")
check("판정 Pod: agent namespace, 서비스 계정 detection-job, 토큰 자동 마운트 끔", (d["namespace"], d["service_account_name"], d["automount_service_account_token"]), ("agent", "detection-job", False))
check("조사 Pod: 서비스 계정 investigation-agent", i["service_account_name"], "investigation-agent")
check("판정 Pod: 판정용 workgroup, 순찰 시각(JUDGE_TICK)은 Airflow 시각 템플릿", (d["env_vars"]["ATHENA_WORKGROUP"], d["env_vars"]["JUDGE_TICK"]), ("wg-detect", TICK_TEMPLATE))
check("조사 Pod: 조사용 workgroup, 모델 ID, 최대 건수 문자열", (i["env_vars"]["ATHENA_WORKGROUP"], i["env_vars"]["BEDROCK_MODEL_ID"], i["env_vars"]["INVESTIGATE_MAX"]),
      ("wg-investigate", GOOD["bedrock_model_id"], "3"))
check("조사 Pod에는 순찰 시각이 없고, 판정 Pod에는 모델 ID가 없음", ("JUDGE_TICK" in i["env_vars"], "BEDROCK_MODEL_ID" in d["env_vars"]), (False, False))
check("두 Pod: 이미지는 각자 것, 실행 명령(cmds)은 이미지 ENTRYPOINT를 쓰므로 지정 안 함", (d["image"], i["image"], "cmds" in d or "cmds" in i), (GOOD["detect_image"], GOOD["investigate_image"], False))
check("두 Pod: 끝나면 Pod 삭제, 로그 가져오기, 결과 전달(xcom) 안 함", (d["on_finish_action"], d["get_logs"], d["do_xcom_push"]), ("delete_pod", True, False))
check("두 Pod: 실행 제한 시간이 5분 주기보다 짧음(판정 3분, 조사 4분)", (d["execution_timeout"], i["execution_timeout"]), (timedelta(minutes=3), timedelta(minutes=4)))
check("두 Pod: 재시도 1번(같은 순찰 번호라 이중 저장 안 됨)", (d["retries"], i["retries"]), (1, 1))
r6 = pod_kwargs(load_config(env(silver_checks_table="silver.order_amount_checks", silver_runs_table="silver.silver_runs")), "detection")["env_vars"]
check("R6 설정이 설정 JSON에 있으면 판정 Pod 환경 변수로 전달됨 (R6_CHECK_NAME은 안 줬으니 없음)",
      (r6.get("SILVER_CHECKS_TABLE"), r6.get("SILVER_RUNS_TABLE"), "R6_CHECK_NAME" in r6), ("silver.order_amount_checks", "silver.silver_runs", False))
check("R6 설정이 없으면 판정 Pod에 R6 환경 변수가 없음, 조사 Pod에는 항상 없음",
      (any(n in d["env_vars"] for _, n in R6_KEYS), any(n in pod_kwargs(load_config(env(silver_checks_table="x.y")), "investigation")["env_vars"] for _, n in R6_KEYS)), (False, False))
check("노드 고정은 hostname을 줄 때만", ("node_selector" in d, pod_kwargs(load_config(env(hostname="node-1")), "detection")["node_selector"]), (False, {"kubernetes.io/hostname": "node-1"}))
check("자원 요구량(임의 값)", RESOURCES["requests"], {"cpu": "250m", "memory": "512Mi"})
try:
    pod_kwargs(cfg, "x")
    check("알 수 없는 역할은 거부", "통과됨", "거부")
except ValueError:
    check("알 수 없는 역할은 거부", "거부", "거부")
envs = json.dumps([d["env_vars"], i["env_vars"]]).lower()
check("Pod 환경 변수에 비밀번호·키·토큰 글자가 없음", any(w in envs for w in ("password", "secret", "token", "access_key", "bearer")), False)

# --- DAG 파일(구문만 읽어 확인) ---
def dag_args(path):
    tree = ast.parse((HERE / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "dag":
                    return {k.arg: ast.literal_eval(k.value) for k in dec.keywords if isinstance(k.value, (ast.Constant, ast.List))}
    return {}


for file, dag_id in (("agent_detection.py", "agent_detection_5min"), ("agent_investigation.py", "agent_investigation_5min")):
    a = dag_args(file)
    check(f"{file}: DAG ID, 5분 주기, 밀린 회차 안 돌림, 동시 1개, 처음엔 paused", (a.get("dag_id"), a.get("schedule"), a.get("catchup"), a.get("max_active_runs"), a.get("is_paused_upon_creation")),
          (dag_id, "*/5 * * * *", False, 1, True))
    text = (HERE / file).read_text(encoding="utf-8")
    check(f"{file}: 실제 환경 값(이미지 주소 등)이 코드에 없음", any(w in text for w in ("amazonaws.com", "arn:aws", "sha256:")), False)

if "--airflow" in sys.argv:                                     # Airflow가 있는 환경에서만: 실제 DAG 파일을 불러온다
    import os
    os.environ[CONFIG_ENV] = json.dumps(GOOD)
    try:
        from airflow.dag_processing.dagbag import DagBag      # Airflow 3
    except ImportError:
        from airflow.models import DagBag
    bag = DagBag(dag_folder=str(HERE), bundle_path=HERE, bundle_name="agent")
    check("Airflow: DAG 파일 불러오기 오류 없음", bag.import_errors, {})
    check("Airflow: DAG 2개", sorted(bag.dags), ["agent_detection_5min", "agent_investigation_5min"])
    for dag_id, dag in bag.dags.items():
        t = dag.tasks[0]
        check(f"Airflow: {dag_id} 작업 1개, Pod 연산자, 서비스 계정", (len(dag.tasks), type(t).__name__, bool(t.service_account_name)), (1, "KubernetesPodOperator", True))

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
