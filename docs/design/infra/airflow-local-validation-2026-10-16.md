# Airflow 로컬 실행 검증

상태: 제안(운영 배포) / 로컬 검증 완료 · 2026-10-16

## 범위

사용자가 승인 화면의 재처리 API·5분 주기 이상 판정 작업을 위한 Airflow를 로컬에서 먼저 검증하도록 요청했다. 공식 Airflow 3.3.2 Python 3.12 digest 이미지, LocalExecutor(parallelism=2), API 1 worker, DAG parser 1개 및 임시 PostgreSQL을 사용한다. 운영 버전/Executor/Auth Manager/메타데이터 DB를 확정하거나 AWS에 배포하지 않는다.

업무 DAG 대신 `cq_replay_probe`와 `cq_five_minute_probe`를 쓴다. 작업은 짧은 대기 후 synthetic JSON을 local volume에 기록한다. Athena/S3/실제 업무 데이터·승인 화면·ground truth 접근 분리는 검사하지 않는다. LocalExecutor 검사이므로 KubernetesExecutor의 파드 생성 시간도 검사하지 않는다.

## 구성 및 자원

상시 memory limits는 API 768MiB, scheduler+LocalExecutor 1536MiB, dag-processor 768MiB, 테스트 DB 384MiB로 합계 3456MiB다. CPU quota 합계는 2.25 vCPU다. DB migration은 별도 1024MiB/1 CPU 컨테이너에서 선행 실행 후 종료한다. Docker 엔진은 8 CPU/약 15.5GiB다. 이는 2 CPU/8GiB EKS 노드의 전체 수용·성능 검증이 아니다.

host port가 없는 내부 Docker network와 매 실행 임의 project·전용 volume을 사용한다. AWS 인증 변수를 제거하고 DB/API 인증정보를 매번 생성해 임시 파일과 컨테이너에만 전달한다. 결과/diagnostics는 비밀값을 가려 Git 제외 `.cache/airflow-local-report.json`에 보존한다. 종료 시 project의 컨테이너·network·volume만 정리하며 이미지 캐시와 다른 프로젝트는 보존한다.

## 수정한 문제와 검증 기준

첫 실행은 SimpleAuthManager의 비밀번호 파일을 read-only로 bind해 API 시작 시 쓰기가 거부됐다. 테스트용 임시 파일만 writable로 바꿨고 정리 성공을 확인했다. 다음 실행은 인증 토큰 생성의 정상 HTTP 201을 200만 기대한 검사기가 실패했으며, 200/201을 허용하도록 수정했다. 해당 실패들은 처리량이나 메모리 부족 실패가 아니다.

수정 후 API 인증, 미인증·잘못된 비밀번호 거부, viewer의 실행 거부, 재처리 두 건 성공·비중첩, 동일 run ID 409 거부, scheduled run 두 건 성공, OOM/재시작 없음 및 정리를 확인했다. 첫 scheduled run은 시작 직후 과거 예약 시각에 대해 실행됐다. 반복 간격 검증을 보강해 활성화 이후의 미래 예약 시각 두 건만 집계하며 logical_date 간격이 300초인지 확인한다. 이는 정시 시작/완료 SLA를 뜻하지 않는다.

SimpleAuthManager의 operator는 테스트 DAG pause 해제를 위해 admin을 사용한다. viewer의 실행 거부만 검증하며 운영의 특정 DAG에 제한한 권한을 검증한 것은 아니다. 동일 run ID 거부도 실제 승인 백엔드의 ID 관리나 업무 재처리의 멱등성을 대신하지 않는다.

## 결과

최종 실행 project `cq-airflow-dfa4403452`에서 모든 검사를 통과했다. DB 초기화부터 API ready까지 84.8초, 전체 검사/정리 500.9초였다. 68개 Docker stats 표본에서 동시 메모리 합의 최고치는 967.8MiB(약 0.95GiB)였다. 컨테이너별 최고치는 API 296.3MiB, scheduler 406.4MiB, dag-processor 204.1MiB, 테스트 DB 90.4MiB였다. 개별 최고치는 서로 다른 시점의 값이며 Docker stats가 노드 전체 RSS나 운영 상한을 뜻하지 않는다.

| 예약 시각(UTC) | 시작 지연 | 실행 구간 | 결과 |
|---|---:|---:|---|
| 2026-10-16 06:45:00 | 0.94초 | 2.31초 | success |
| 2026-10-16 06:50:00 | 2.83초 | 2.59초 | success |

두 run 모두 DAG 활성화 이후의 예약 시각이며 logical_date/run_after 간격은 300초다. 시작 직후 이전 예약 시각으로 성공한 run은 이 표에서 제외했다. 재처리 API 두 건은 총 57.2초에 완료했고 실행 구간 비중첩을 확인했다. 토큰 인증·미인증/잘못된 비밀번호 거부·viewer 실행 403·중복 run ID 409·OOM=false/재시작=0 및 project 정리 성공을 확인했다.

별도 Kafka compact smoke와 겹친 구간에는 Airflow 4개 및 Kafka 검사 4개 컨테이너가 함께 실행되는 10개 표본을 관측했다. 두 project가 함께 존재한 16개 표본에서 메모리 합의 관측 최고치는 약 2096.6MiB였다. Kafka fixture가 Strimzi 운영자·Kubernetes를 대신하지 않으며 전체 CDC 검사 내내 Airflow가 실행됐다는 뜻은 아니다. 실제 업무 부하·S3 Sink는 이 수치에 포함되지 않는다.

Kafka project `cq-cdc-3c56f15215`도 전체 compact 검사를 통과했다. mTLS/ACL, snapshot/insert/update/delete, 1000행 burst(14.2초, consumer 시작/관측 포함), Connect 중단 후 전달, Kafka 재생성 후 메시지/offset 보존, metrics 및 OOM/재시작 검사를 통과했고 해당 project 자원을 정리했다. 로컬 Airflow/Kafka 동시 실행 관측을 단일 EKS 노드의 성능 보장으로 해석하지 않는다.

최종 Python 구문 검사와 git diff --check를 통과했다. Terraform·Helm 배포 코드를 바꾸지 않아 기존 Terraform 전체 검사나 이미지 취약점 검사는 반복하지 않았다. AWS apply·원격 push·PR 변경은 수행하지 않았다.

## 배포 전 남은 검증

- 운영용 Auth Manager·DAG별 실행/조회 권한, 승인 백엔드 경로·Secret·감사 기록.
- Airflow 메타데이터 DB·전용 계정·연결 수·백업 및 RDS 공유 여부.
- 실제 Athena/Glue/S3 역할과 작업, 결과 저장·조회 범위, 스캔량/지연/비용, 에이전트와 채점용 결과 경로 분리.
- Airflow/Kafka/Connect/운영자/시스템 Pod의 실제 requests/limits·EKS scheduling·노드 확장/교체·CPU credits·볼륨/로그.
- 큰 조회 결과·작업 실패/재시도·5분을 넘는 실행·재처리와 정기 작업 동시 실행의 업무 의미.

실행: `python -X utf8 infra/platform/airflow/local-smoke/check.py`.

근거: [Airflow Docker](https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html), [SimpleAuthManager](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html), [API 인증](https://airflow.apache.org/docs/apache-airflow/3.3.2/security/api.html).
