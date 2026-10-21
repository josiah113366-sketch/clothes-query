# 작업 지시서: infra/airflow-runtime

상태: 개발용 Airflow 실제 설치·합성 검증 완료 / 업무 DAG 연결 대기 / 미푸시

## 사용자 결정과 범위

기존 EKS에 Airflow를 설치하고 기존 RDS 안의 별도 DB·계정을 사용한다. 인증은 개발용 Simple Auth Manager이며 접속은 port-forward로 시작한다. 판정·조사는 기존 `agent` namespace의 별도 Pod/ServiceAccount를 사용한다. 사용자의 설치 진행 요청에 따라 실제 변경을 수행했다. CI/CD·비용 알림 보류는 유지하며 PR 승인·머지는 팀원이 한다.

업무용 DAG·판정/조사 앱·Spark job 구현은 포함하지 않는다. 새 노드·ALB·PVC·DB 서버를 만들거나 기존 업무 테이블을 변경하지 않는다. API 전용 taint를 유지하고 Airflow는 현재 compute 노드 hostname에 고정해 이번 검증의 자동 증설을 막는다. 이 고정은 노드 교체 대응을 제한하므로 향후 용량/가용성 설계에서 다시 판단한다.

## 구현

- 공식 Helm 1.22.0 / Airflow 3.3.2 Python 3.12, LocalExecutor, API·scheduler·DAG processor 각 1개. 본체 requests 300m/1152Mi, migration Job 50m/256Mi. 작업 병렬 한도 1, 업데이트 Recreate로 업데이트 중 중단 가능.
- 기존 RDS의 `airflow_meta` DB·역할, 연결 한도 16. NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION, PUBLIC DB/schema 권한 제거, 기존 업무 테이블 SELECT 권한 없음 검증. RDS CA와 TLS verify-full 사용. RDS 재부팅·사양 변경 없음.
- Secrets Manager 원본과 Kubernetes Secret 5개(metadata/Fernet/API/JWT/Simple Auth). master 자격 증명을 담은 일회성 bootstrap Secret·Pod는 삭제했다. 실제 비밀번호·ARN·계정·버킷·엔드포인트·이미지 digest·hostname은 비공개 파일에만 보관한다.
- S3 `airflow-logs/`에 task 로그 저장. 기존 `workload-access` 입력을 보존하고 scheduler 읽기/쓰기와 API 읽기용 정책·역할·Pod Identity 6개만 plan 확인 후 추가했다. 적용 후 변경 없음 plan을 확인했고 비공개 deployment tfvars에도 보존했다.
- scheduler는 `agent` Pod 생성·조회·삭제 및 로그 조회만 가능하다. agent Secret 조회와 kafka namespace Pod 생성은 실제 RBAC 검사에서 거부됐다. 기존 `agent/detection-job`, `agent/investigation-agent` Pod Identity를 재사용한다.
- 내장 PostgreSQL·Redis·PgBouncer·triggerer·StatsD·추가 ALB·PVC 비활성. LocalExecutor 기본 worker PVC 옵션도 껐다. 최종 렌더 14개 객체, Deployment 3개와 migration Job이며 서버 dry-run 통과. 모든 init/container 이미지 digest를 고정했다.

## 발견과 수정

1. DB pool size 1/overflow 1은 migration에서 QueuePool timeout이 발생했다. size 3/overflow 2로 수정했다. 전체 역할 연결 한도 16은 유지했다.
2. ConfigMap 디렉터리 내부 symlink를 DAG processor가 재귀 루프로 탐지했다. DAG 단일 파일을 subPath로 마운트했다. 변경 후 본체 rollout이 필요하다.
3. Simple Auth Manager는 기존 비밀번호 파일도 쓰기 모드로 연다. Secret을 직접 읽기 전용 마운트하면 PermissionError가 발생한다. API init에서 Secret 원본을 Pod 전용 emptyDir로 복사하고 권한을 0600으로 지정했다. 파일 내용은 출력하지 않는다.
4. API 기본 시작 점검 유예가 짧아 초기 기동이 재시작됐다. 유예를 5분으로 늘렸다. 정상 상태/인증 검사는 끄지 않았다.
5. 임시 복구 중 namespace가 생략된 Helm 렌더를 kubectl로 적용해 default에 Deployment 3개와 ConfigMap 1개를 잘못 만들었다. 전체 last-applied 내용을 생성한 렌더와 대조하고 UID를 기록했다. 자동 승인 검토가 삭제를 차단해 사용자에게 명시적 승인을 받았으며, 동일 UID precondition으로 확인된 4개만 삭제했다. default의 관련 Deployment/Pod가 0개임을 확인했다. 올바른 namespace의 직접 수정은 최종 Helm upgrade로 관리 상태와 일치시켰다.

실패한 최초 설치는 atomic 복구를 확인했다. Helm 복구는 사전에 준비한 DB·Secret·IAM을 되돌리지 않는다. 완료된 비-hook migration Job은 이후 template 변경 시 immutable 필드 충돌을 피하도록 성공 상태를 확인해 정리하고 재실행했다. 실패/실행 중 Job을 무조건 지우지 않는다.

## 실제 검증 결과: 2026-10-21 Tokyo

- 본체 3개 Ready, 최종 기동 후 restart 0, Helm 설치/업그레이드 완료. 노드 2개 유지. Kafka 6/6, 기존 API 1/1 Ready/restart 0.
- 공식 이미지에서 Amazon provider 9.36.0, Kubernetes 10.22.0, PostgreSQL 7.0.2 및 SDK import 확인. 실제 EKS 1.36에서 아래 합성 검증 성공. 공식 테스트 Kubernetes 목록은 1.35까지이므로 이 결과를 공식 지원 범위 확대로 간주하지 않는다.
- operator/admin·observer/viewer·approval/user 토큰 발급 성공. 미인증 조회 거부, 잘못된 비밀번호 거부, viewer 실행 거부, approval 실행 허용, 중복 dag_run_id 409 확인. DAG import 오류 0.
- `infra_airflow_access_probe`: 실제 승인 계정 호출 → scheduler → detection/investigation Pod 순차 실행 → 모두 성공. 각 전용 IAM 역할과 Gold B 목록 조회·ground_truth 접근 거부를 확인했다. 실행 약 109초, 첫 Pod task 약 60초, 두 번째 약 15초였다. 업무 Athena 쿼리 시간은 포함하지 않는다.
- API Pod의 전용 로그 읽기 역할로 S3 로그 2개를 읽어 두 Pod의 성공 증거를 확인했다. 로그 원문·토큰·비밀번호는 공개 출력하지 않았다.
- `infra_airflow_five_minute_probe`의 5분 간격 logical date 실행 3회 성공. 설치/재시작 후 대기 실행은 약 93초·17초, 정상 03:30 UTC tick은 03:30:01.529에 시작해 약 3.4초 만에 끝났다. 아주 작은 합성 작업의 결과이며 실제 판정 잡의 5분 SLA를 입증하지 않는다.
- 검증 DAG 2개 다시 pause. 임시 agent Pod 0개, 잘못 만든 default Airflow Pod 0개. 업무 데이터·정답표에 합성 행/파일을 쓰지 않았다. Airflow 실행 이력과 S3 task 로그는 검증 운영 기록으로 남는다.
- 검증 후 관측점에서 compute 노드 working set 약 5232Mi, Airflow 본체 합계 약 1218Mi. 이는 단일 관측값이며 최고치나 업무 부하 예산이 아니다. DB 연결은 관측 시 Airflow 6개/한도 16이었다.
- Ruff check/format, YAML 문법, Helm schema/render·서버 dry-run, diff 점검 완료. 실제 계정·엔드포인트·비밀값이 추적 파일에 없는지 확인 후 로컬 커밋한다.

## 팀원에게 넘길 것과 남은 일

[접속·설치 안내](../../infra/platform/airflow/README.md)의 port-forward와 인증/API 방식을 사용한다. 비밀번호는 별도 비공개로 전달한다. 실제 재처리/판정 DAG ID, 입력 범위와 교체 완료 조건, 앱 이미지·업무 SQL을 받아 DAG 공급·실행 시간·자원을 검증해야 한다. 이번 합성 DAG를 업무 DAG로 오인하지 않는다.

Gold B Glue DB/테이블 계약, 판정용 쓰기 prefix·쓰기 방식은 별도 미확정 입력이며 이번 설치가 생성·확정하지 않는다. 조사·판정 ServiceAccount의 실제 권한 분리는 기존 gold-b-access 작업을 전제로 한다. 개발자 IAM 사용자에게 이미 광범위한 그룹 권한이 있는 사실도 그대로다. 업무 DAG를 직접 이어 재판정하는 구현은 담당자와 계약 후 가능하며, 임시 5분 확인 방식과 구분한다.

PR #14의 사용자 클릭과 알려진 SQL 후속 사항을 인지했으며 해당 PR을 승인·머지·수정하지 않았다. 이 브랜치도 push·PR 승인·머지를 수행하지 않는다.

## 참고

- [공식 발표](https://airflow.apache.org/announcements/)
- [Helm 1.22.0](https://airflow.apache.org/docs/helm-chart/1.22.0/index.html)
- [Airflow 3.3.2 요구 조건](https://airflow.apache.org/docs/apache-airflow/3.3.2/installation/prerequisites.html)
- [Simple Auth Manager](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html)
