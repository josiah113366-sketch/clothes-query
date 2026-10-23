# agent/dags

판정 잡과 조사 에이전트를 **5분마다 Airflow가 실행**하게 연결하는 DAG 2개다. 코드는 각 이미지 안에 있고(`agent/detect/run_job.py`, `agent/investigator/run_investigation.py`), 이 폴더는 **실행만 연결**한다. 새 DAG는 처음에 **paused**로 등록된다.

## 쉬운 설명: 알람 시계 두 개

5분마다 울리는 알람 시계가 두 개 있다. 하나는 "경비원(판정 잡)을 한 바퀴 돌게" 하고, 다른 하나는 "조사관(조사 에이전트)에게 아직 안 본 사건을 넘기게" 한다. 시계는 Pod(일회용 작업 상자)를 하나 띄워 일을 시키고 끝나면 치운다. 둘을 따로 둔 이유는 조사가 오래 걸려도 **판정 순찰이 밀리지 않게** 하려는 것이다.

## 어느 부분이 어느 코드인가

| 하는 일 | 코드 |
|---|---|
| 판정 DAG (`agent_detection_5min`) | `agent_detection.py` |
| 조사 DAG (`agent_investigation_5min`) | `agent_investigation.py` |
| 설정 읽기, Pod 설정 만들기 | `agent_common.py` (`load_config`, `pod_kwargs`) |
| 시험 | `test_dags.py` |
| Airflow가 시험 파일을 DAG로 읽지 않게 | `.airflowignore` |

## 설정: 환경 변수 `AIRFLOW_AGENT_CONFIG` (JSON)

실제 환경 값은 Git에 넣지 않고 인프라 담당이 **업무용 ConfigMap**으로 공급한다(확인용 DAG가 `AIRFLOW_INFRA_PROBE_CONFIG`를 쓰는 것과 같은 방식). ConfigMap은 비밀 저장소가 아니다. 비밀번호·토큰은 넣지 않는다. AWS 권한은 Pod의 ServiceAccount와 Pod Identity가 준다.

| 키 | 필수 | 뜻 |
|---|---|---|
| `detect_image` | 필수 | 판정 이미지 주소(digest 고정 권장) |
| `investigate_image` | 필수 | 조사 이미지 주소(digest 고정 권장) |
| `detect_workgroup` | 필수 | 판정용 Athena workgroup 이름 |
| `investigate_workgroup` | 필수 | 조사용 Athena workgroup 이름 |
| `region` | 필수 | AWS 리전 |
| `bedrock_model_id` | 필수 | 모델(프로필) ID. 현재 결정: Claude Haiku 4.5의 `jp.` 프로필 |
| `investigate_max` | 선택 | 한 번에 조사할 이상 수(기본 3, 비용 상한) |
| `hostname` | 선택 | 새 노드가 생기지 않게 Pod를 기존 노드에 고정하고 싶을 때만 |

빠진 키가 있으면 DAG 파일을 불러올 때 **빠진 키 이름을 모두 적은 오류**가 나서 Airflow 화면의 import 오류로 보인다.

## 실행 방식

| | 판정 | 조사 |
|---|---|---|
| DAG ID | `agent_detection_5min` | `agent_investigation_5min` |
| 주기 | `*/5 * * * *` | `*/5 * * * *` |
| namespace / 서비스 계정 | `agent` / `detection-job` | `agent` / `investigation-agent` |
| 넘기는 환경 변수 | `ATHENA_WORKGROUP`, `AWS_REGION`, `JUDGE_TICK` | `ATHENA_WORKGROUP`, `AWS_REGION`, `BEDROCK_MODEL_ID`, `INVESTIGATE_MAX` |
| 작업 제한 시간 | 3분 | 4분 |
| 재시도 | 1번(30초 뒤) | 1번(30초 뒤) |

- `JUDGE_TICK`은 Airflow의 논리 시각(`data_interval_end`)이다. 순찰 번호가 이 시각으로 정해져서, 실패한 작업을 다시 돌려도 **같은 번호**가 되어 이상 줄이 두 번 쌓이지 않는다. 수동 실행처럼 논리 시각이 없으면 실행 요청 시각을 쓴다(순찰 번호는 5분 단위로 내려서 정한다).
- `catchup=False`, `max_active_runs=1`: 밀린 회차를 한꺼번에 돌리지 않고, 한 번에 하나만 돈다.
- 컨테이너 실행 명령은 이미지의 `ENTRYPOINT`를 그대로 쓴다.

## 시험

```
python3 agent/dags/test_dags.py              # Airflow 없이(설정 읽기, Pod 설정, DAG 파일의 주요 값)
python3 agent/dags/test_dags.py --airflow    # Airflow가 설치된 환경에서 실제 DAG 파일을 불러와 본다
```

## 알아야 할 것 (한계)

- **실제 클러스터에서는 실행해 보지 않았다.** 이 환경에서는 Airflow 3.3.2의 DagBag으로 DAG 2개가 오류 없이 불러와지는 것까지 확인했다.
- 자원 요구량(요청 250m CPU / 512Mi, 제한 500m / 1Gi)과 제한 시간(3분, 4분)은 **측정 전의 임의 값**이다. 실제 실행 시간을 재영 님과 확인해 5분 주기가 가능한지 보고 조정한다.
- 이미지가 아직 ECR에 올라가지 않았다. 이미지 digest와 업무용 ConfigMap이 공급돼야 실제로 돈다.
- 재처리 DAG와 승인 화면의 Airflow 호출은 이 폴더가 아니다.
