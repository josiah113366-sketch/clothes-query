# Airflow 개발 실행 기반

기존 EKS의 `airflow` namespace에 공식 Helm 1.22.0 / Airflow 3.3.2 Python 3.12 이미지를 사용한다. 기존 RDS 안의 전용 `airflow_meta` DB·계정을 사용하며 개발 인증은 Simple Auth Manager다. 실제 배포·검증 상태는 [작업 기록](../../../docs/tasks/infra-airflow-runtime.md)에 남긴다. 업무용 재처리·판정 DAG는 각 담당자가 구현한다.

## 구성과 의존성

- [development-values.yaml](development-values.yaml): LocalExecutor, API·scheduler·DAG processor 각 1개, 본체 requests 합계 300m/1152Mi. 본체는 compute 노드풀만 사용한다. 비공개 runtime override에서 현재 노드 hostname을 지정해 이번 검증이 새 노드를 만들지 않게 한다.
- 내장 PostgreSQL·Redis·PgBouncer·triggerer·StatsD·추가 ALB·PVC는 사용하지 않는다. `workers.celery.persistence`도 꺼서 LocalExecutor scheduler에 기본 PVC가 생기지 않게 한다. 업데이트 전략은 Recreate라 업데이트 중 중단될 수 있다.
- [prepare_metadata.py](prepare_metadata.py): 일회성 비공개 Pod에서 전용 DB·계정만 생성·검증한다. 역할은 superuser/DB 생성/역할 생성/복제 권한이 없고 연결 한도는 16이다. 기존 업무 테이블을 변경하지 않는다. RDS CA와 `sslmode=verify-full`을 사용한다.
- metadata connection·Fernet·API secret·JWT·Simple Auth 비밀번호를 각각 기존 Kubernetes Secret 참조로 공급한다. 원본은 Secrets Manager에서 비공개 관리한다. 실제 값·계정·엔드포인트·이미지 digest·버킷은 공개 파일에 쓰지 않는다.
- task 로그는 기존 S3의 `airflow-logs/`로 보낸다. `workload-access`의 scheduler 역할은 해당 prefix 읽기/쓰기, API 역할은 읽기만 허용한다. 이 두 binding은 기존 비공개 tfvars에도 유지해야 한다. 새 CloudWatch 로그 수집은 추가하지 않는다.
- [agent-pod-rbac.yaml](agent-pod-rbac.yaml): scheduler에 `agent` namespace Pod 생성·조회·정리와 로그 읽기만 허용한다. Secrets 읽기나 다른 namespace Pod 생성은 허용하지 않는다. 판정·조사 Pod는 기존 `agent/detection-job`, `agent/investigation-agent` ServiceAccount와 각각의 EKS Pod Identity를 사용한다.

## 설치 순서

1. Tokyo 계정·클러스터와 기존 node/Pod 요청량, RDS 부하·연결 수를 확인한다. API 전용 taint는 유지한다.
2. 전용 DB·계정, CA ConfigMap, 인증 Secret 5개를 비공개 공급한다. master 비밀번호가 필요한 bootstrap Secret/Pod는 준비 직후 삭제한다.
3. S3 task 로그용 Pod Identity와 위 RBAC를 준비한다. `gold-b-access`의 기존 agent namespace/ServiceAccount가 먼저 있어야 한다.
4. 이미지 digest·현재 노드 hostname·S3 log 경로를 gitignored `runtime.local.yaml`로 공급한다. 공식 chart archive checksum을 index와 대조하고 이미지를 digest로 고정한다.
5. 합성 검증 DAG를 ConfigMap `airflow-infra-dags`, 이미지/노드 설정을 `airflow-infra-probe-runtime`으로 공급한다. 공개 DAG 파일에는 실행 이미지 URI·hostname을 넣지 않는다.
6. `helm template`와 서버 dry-run에서 새 PVC/Ingress/DB/ClusterRole가 없는지, init/Job를 포함한 requests와 이미지 고정을 확인한다. 그 뒤 `helm upgrade --install airflow <검증한-chart> -n airflow -f development-values.yaml -f runtime.local.yaml --atomic --wait --wait-for-jobs --timeout 10m`을 실행한다.

Helm 렌더에 `metadata.namespace`가 없는 객체가 있으므로 렌더를 kubectl로 검사·적용할 때도 `-n airflow`를 명시한다. DAG는 ConfigMap 디렉터리 대신 `subPath`로 단일 파일을 마운트해 Airflow의 재귀 링크 탐색을 피한다. 이 파일을 갱신하면 해당 파일을 사용하는 본체 Pod를 재시작해야 한다. API 시작 점검 유예는 5분이며 인증/정상 상태 점검을 끄지 않는다.

Simple Auth Manager는 기존 비밀번호 파일도 쓰기 모드로 연다. 읽기 전용 Secret을 직접 지정하면 PermissionError가 나므로, API init에서 Secret 원본을 Pod 전용 emptyDir의 권한 0600 파일로 복사한다. 원본과 실제 값은 로그에 출력하지 않는다. API 재생성 시 동일한 Secret 원본에서 복구한다.

DB pool은 프로세스별 size 3/overflow 2다. size 1/overflow 1은 실제 migration에서 QueuePool timeout이 발생해 사용하지 않는다. 전체 DB 연결 한도·현재 부하는 별도로 관측하며 업무 동시성을 늘릴 때 재검증한다. Helm의 atomic 복구는 별도로 준비한 DB·Secret·IAM·ConfigMap을 지우거나 DB migration을 되돌리지 않는다.

## 접속과 작업 호출

```powershell
kubectl -n airflow port-forward svc/airflow-api-server 8080:8080
```

브라우저에서 `http://localhost:8080`을 연다. 비밀번호는 별도 비공개로 전달한다. `operator`는 admin, `observer`는 viewer, `approval`은 user다. Simple Auth는 개발용 고정 역할이라 업무 DAG별 세밀한 allowlist나 운영용 사용자 관리를 대신하지 않는다.

승인 백엔드는 `POST /auth/token`으로 토큰을 받고 `POST /api/v2/dags/{dag_id}/dagRuns`에 고유 `dag_run_id`와 실제 교체 범위 `conf`를 보낸다. EKS 내부 주소는 `http://airflow-api-server.airflow.svc.cluster.local:8080`이다. 이 주소를 외부에 노출하는 ALB는 만들지 않는다. 실제 업무 DAG ID·입력 계약과 승인 백엔드 네트워크 경로는 담당자와 연결해야 한다.

## 합성 검증과 한계

[dags/infra_probe.py](dags/infra_probe.py)는 업무 DAG가 아닌 설치 확인용이다. `infra_airflow_access_probe`는 두 agent ServiceAccount를 순차 실행해 Pod Identity·Gold B 목록 조회·정답표 거부를 검사한다. `infra_airflow_five_minute_probe`는 5분 cron 실행만 검사한다. 생성 시 paused이며 검증 후 다시 pause하고 임시 agent Pod는 삭제한다. 업무 테이블/정답표를 쓰거나 실제 Athena 업무 쿼리를 실행하지 않는다.

Kafka와 같은 단일 compute 노드를 공유하고 본체 병렬 작업 한도는 1이다. 이 설정은 고가용성이나 업무 5분 SLA를 보장하지 않는다. 실제 판정 이미지·Athena 쿼리·S3 쓰기 prefix가 확정되면 CPU/메모리/DB 연결과 전체 실행 시간을 다시 측정해야 한다. 조사 역할의 `ground_truth/` 차단과 별개로, 광범위한 IAM 그룹 권한이 있는 개발자 사용자의 권한을 제한했다고 주장하지 않는다.

[과거 로컬 검증](local-smoke/README.md)은 별도 일회용 PostgreSQL과 Docker 환경의 결과다. 당시의 로컬 성공을 현재 EKS 업무 실행 성공으로 간주하지 않는다.
