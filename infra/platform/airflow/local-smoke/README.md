# Airflow 로컬 smoke 검사

공식 Airflow 3.3.2 Python 3.12 이미지와 PostgreSQL을 digest로 고정했다. 고유 Compose project, 내부 전용 network, 테스트 전용 named volume을 생성하고 종료 시 해당 project 자원만 정리한다. host port를 열지 않고 AWS/TF/Kubernetes 인증 변수를 제거한다. 이미지 다운로드는 Docker가 수행하며 작업 컨테이너 network에는 인터넷 경로가 없다. 인증정보는 매 실행 생성한 임시 파일에만 두고 출력/보고서에서 제외한다.

저장소 루트에서 Docker Desktop Linux 엔진과 Python으로 실행한다. 외부 Docker context 및 DOCKER_HOST/DOCKER_CONTEXT override는 거부한다.

```powershell
python -X utf8 infra/platform/airflow/local-smoke/check.py
```

전체 실행은 이미지 다운로드·DB 초기화에 더해 실제 5분 예약 두 번을 기다리므로 약 6~15분 걸릴 수 있다. API는 내부 network에서만 호출한다. 사용자 브라우저용 접속 화면을 제공하는 실행은 아니다. 전체 결과와 Docker stats는 Git 제외 `.cache/airflow-local-report.json`에 기록하고 실패 시 비밀값을 가린 diagnostics를 같은 파일에 보존한다. 종료 시 metadata/log volume도 삭제하므로 재실행은 새 DB에서 시작한다. 이미지 캐시는 보존한다.

## 검사 범위

- 메타데이터 DB migration, API·scheduler·dag-processor 시작.
- 토큰 인증, 미인증·잘못된 비밀번호 거부, viewer의 DAG 실행 거부.
- API로 재처리 probe DAG 실행, 같은 run ID 중복 요청 409 거부.
- 재처리 두 건의 성공·실행 구간 비중첩(max_active_runs=1).
- `*/5 * * * *`, catchup=False인 probe DAG가 활성화 이후의 예약 시각 두 번에 성공하고 logical_date 간격이 300초인지 확인. 시작 직후 과거 예약 시각으로 실행된 run은 두 번 집계에서 제외한다.
- 컨테이너별 CPU/memory 제한, Docker stats, OOM/재시작 여부, project 자원 정리.

운영자 probe는 테스트 DAG pause 해제를 위해 admin을 사용한다. 운영의 특정 DAG 실행만 허용하는 Auth Manager/RBAC는 별도다. 중복 run ID 거부는 승인 처리 백엔드가 동일 승인에 일관된 ID를 사용할 때 유용하며 업무 재처리 자체의 멱등성을 보장하지 않는다.

## 자원과 한계

| 서비스 | 메모리 한도 | CPU quota |
|---|---:|---:|
| API(1 worker) | 768MiB | 0.5 |
| scheduler + LocalExecutor(parallelism=2) | 1536MiB | 1 |
| dag-processor(parsing_processes=1) | 768MiB | 0.5 |
| PostgreSQL fixture | 384MiB | 0.25 |
| 상시 합계 | 3456MiB | 2.25 |

DB migration 컨테이너는 별도 선행 실행(1024MiB/1 CPU) 후 종료한다. Docker 엔진 자원은 보고서에 기록한다. 위 제한은 컨테이너별 quota이며 t3a.large의 2 CPU/8GiB EKS 노드를 재현한 것이 아니다. Kafka/Connect·Strimzi·Kubernetes/CNI·전체 스토리지 사용량은 이 검사 밖이다. 실제 업무에서 Athena 결과를 큰 Python 데이터로 읽거나 여러 DAG/재시도를 동시에 돌리면 사용량이 달라진다.

probe task는 대기 후 synthetic JSON을 로컬 로그 볼륨에 저장한다. Athena·S3·실제 데이터·정답표 IAM·승인 화면·KubernetesExecutor 파드 기동·EKS IAM/RDS/EBS는 테스트하지 않는다. 5분 logical_date 간격과 성공은 정시 시작/5분 내 업무 완료 SLA가 아니다. 재처리/이상 판정 업무 DAG는 팀원 담당이다.

근거: [Airflow Docker 안내](https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html), [SimpleAuthManager](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html), [cron](https://airflow.apache.org/docs/apache-airflow/3.3.2/authoring-and-scheduling/cron.html).
