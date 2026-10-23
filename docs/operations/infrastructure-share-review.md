# 인프라 통합 브랜치 공유 준비

상태: 통합·검증 완료, 사용자 요청에 따라 push. PR 생성·기존 PR 변경·승인·머지는 미실행
대상 브랜치: infra/applied-state-sync
기준 main: 85600ca (#95·#98·#99·#100 포함)

2026-10-24 추가: 사용자 요청으로 CI 수정은 제외하고 Gold B 연결 기반을 준비했다. ECR gold-b 저장소와 전용 실행 역할 3개, 계정/RBAC·Kafka TLS 2세트·Airflow 1슬롯 pool을 적용·검증했다. #100 DAG의 Spark taint 허용 코드는 이 브랜치에 보완했다. 아직 최종 이미지 digest와 checkpoint가 없어 업무 실행 설정은 공급하지 않았고 노드·업무 Pod를 시작하지 않았다. 자세한 결과는 [실행 기반](../../infra/platform/gold-b/README.md)과 [작업 기록](../tasks/infra-applied-state-sync.md)을 따른다.

2026-10-24 draft 대조 결과: #73은 기존 통합에 포함됐지만 #74의 독립 gold-b-catalog 스택·DAG 공급/배치 검사·접근 테스트 등 26개 경로가 누락돼 있었다. 원격 #74 head를 실제로 병합해 누락분과 기존 이력을 보존했다. 충돌에서는 현재 적용한 Dashboard 모델 레지스트리 읽기와 JP Haiku 설정을 유지했다. 따라서 기존 두 draft를 단순 폐기하지 않고, 그 내용까지 포함한 통합 브랜치를 공유 대상으로 삼는다.

## 검토 목적

실제로 적용한 운영·실행 기반이 개별 로컬 브랜치에 흩어져 있어 이전 main으로 apply하면 Spark 풀이나 실행 권한·관리 설정을 되돌릴 수 있다. 원본 여덟 후속을 최신 main에 통합하고, 현재 두 노드 구조·#95 카탈로그 배포·확인된 연결과 미완료 업무 검증을 구분했다. 업무 계산·에이전트 규칙·DAG 코드는 main 그대로다.

기존 브랜치는 보존했다. root의 미커밋 Gold B 이미지 실험은 통합하지 않았다. 실제 Helm values·Secret·개인 IP/이메일·state·plan·업무 원문은 공유하지 않는다.

## 리뷰 순서

| 순서 | 묶음 | 집중해서 볼 부분 |
|---|---|---|
| 1 | 운영 도구 | 기존 API 노드의 모니터링·Argo CD, 선택적 이메일 경보. 앱 자동 CD는 미연결 |
| 2 | Kafka·노드 예약 | CPU 예약 1,900m→1,400m, 단일 broker PDB, 7일/20GiB 유지, 공용 노드 한 대 종료 기록 |
| 3 | 실행 권한 | 기존 state 주소의 dashboard/spark/collector 접근, S3 prefix·Pod Identity·ECR push 범위 |
| 4 | 런타임 연결 | 판정·조사 digest/ConfigMap 준비, 기본 Spark 이미지·전용 풀 enabled=true, v2 수집기 |
| 5 | 운영 점검과 기록 | 한 번 실행하는 --pipeline 점검, 장애 복구 안내, #95 실제 반영 결과와 팀원 대기 항목 |

## 기존 #73/#74 처리안

| 기존 PR | 원래 목적 | 현재 정리 |
|---|---|---|
| #73 infra/operations-tools-share | 모니터링·Argo CD 설치 코드와 검증 공유 | 전체 원격 head가 통합 브랜치에 포함됨. 후속 경보·복구·점검도 추가됨 |
| #74 infra/data-runtime-share | Airflow Git DAG·승인 접근·Gold B DB 및 상태 기록 공유 | 빠진 DB 스택·배치 검사 등을 추가 병합해 원격 head 전체 이력을 보존함 |

지금 올릴 대상은 infra/applied-state-sync 한 개다. 여덟 적용 후속과 두 draft를 따로 다시 push/PR할 필요는 없다. 과거 CICD/비용 후보·중지한 Gold B 이미지 실험과 기타 보류 브랜치는 올릴 대상으로 판단하지 않고 보존한다.

제안: 새 통합 브랜치로 검토 대상을 하나로 정하고, 팀원이 내용과 이력을 확인한 뒤 기존 draft #73/#74를 중복 초안으로 정리한다. 새 PR 생성 및 기존 PR 종료는 사용자가 요청한 뒤에만 진행한다. 기존 PR을 먼저 닫거나 head를 강제로 덮어쓰지 않는다. 이 문서는 처리안이며 GitHub 작업을 실행하지 않는다.

## PR 제목 초안

infra: 실제 적용된 운영·데이터 실행 기반과 상태 점검 통합

## PR 본문 초안

실환경에 적용한 인프라 후속이 여러 로컬 브랜치에 흩어져 있어 이전 main의 공유 설정으로 apply하면 Spark 풀·권한·관리 설정을 되돌릴 수 있었습니다. 적용 후속 8개를 최신 main에 통합해 현재 배포 설정과 검증 기록을 한 곳에서 검토하도록 정리했습니다.

모니터링·Argo CD·이메일 경보, Spark/ECR/S3 실행 권한, v2 지연 수집기, 판정·조사 및 대시보드 연결, CPU 예약 축소를 포함합니다. 현재 API medium 1대와 공용 large 1대이며 Spark 전용 풀은 작업 시 생성됩니다. #95 원장 컬럼 5개·뷰 4개는 실제 반영했고 이후 판정 예약 실행도 성공했습니다. 업무 코드는 main과 동일합니다.

기존 점검에 --pipeline 옵션을 추가해 노드 예약/실사용·커넥터·수집기·원장 객체·Airflow 실행 상태를 한 명령으로 확인합니다. 미배포/paused는 WAITING, 조회 실패는 UNKNOWN으로 표시하며 업무 실행·자동 복구·배포는 하지 않습니다. Gold B 상시 Spark와 조사·재처리·Silver 공개/R6·SageMaker 전체 검증에는 팀원 입력이 아직 필요합니다.

검증:

- Terraform 22 roots init/validate와 mock plan 93개 통과. 실제 state 비교 9개 스택 managed resource 변경 없음.
- draft #74 누락 보완 후 재검증: 23 roots init/validate·mock plan 97개 통과. gold-b-catalog/dashboard-access/gold-b-access 실제 plan 모두 변경 없음. Airflow 공유값과 실제 비공개 overlay 렌더에서 Deployment 3개·migration Job 1개의 공용 풀 배치 및 새 노드/PVC 없음 확인. Helm upgrade는 실행하지 않았음.
- 통합 시 Python 검사 49개, Kafka/monitoring/Argo CD Helm 및 Prometheus 검사 통과.
- 후속 #95 관련 SQL/DDL 회귀 40개, 실제 판정 역할 조회 및 배포 뒤 00:10/00:15 예약 실행 성공.
- 추가 상태 점검 테스트 15개 통과. 실제 첫 실행 OK 34/INFO 5/WAITING 6, 경고·확인 불가 없음. 두 번째 실행의 사용량 조회 UNKNOWN은 별도 metrics API 재조회에서 정상 응답했으며 실패를 정상으로 숨기지 않습니다.
- 원격/Linux CI는 push 전이므로 아직 이 통합 head에서 실행하지 않았습니다. 로컬 결과가 원격 CI를 대신하지 않습니다.

공유에는 인증 비밀·개인 입력·실제 state/plan을 포함하지 않습니다. 기존 state/backend 주소와 앱 코드를 유지합니다. Kafka는 단일 broker라 HA가 아니며 CPU/메모리와 미연결 서비스는 추가 실측이 필요합니다. Argo CD의 앱 자동 배포·추가 상시 노드·GPU Job은 이번 후속에서 시작하지 않았습니다.

## 공유 후 순서

사용자가 push/PR을 요청하면 해당 시점 main을 다시 대조하고 차이에 맞는 검사를 수행한다. 팀원이 검토·승인/머지한다. main 반영 전에는 오래된 compute enabled=false나 일부 map만 있는 local var-file로 apply하지 않는다. 반영 후에도 전체 plan을 새로 확인하고 예상 밖 삭제·교체가 있으면 적용하지 않는다.
