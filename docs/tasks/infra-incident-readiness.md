# Kafka·CDC·RDS 복구 준비와 기존 경보 보강

상태: 이메일 연결 적용·SNS 전송 및 구독 확인 완료 · 브랜치: `infra/incident-readiness` · 최신 반영 main: `473303a`

## 범위

사용자가 장애 대응 우선순위 1(복구 절차)·2(장애 감지)부터 진행하도록 요청했다. 중지한 Gold B 이미지 작업은 원래 작업 트리에 그대로 보존하고 별도 worktree에서 기존 운영 도구 브랜치와 최신 main을 반영했다. 새 노드·유료 모니터링 서비스·CloudWatch Logs·외부 메시지/알림 수신자를 추가하지 않는다. Terraform apply·업무 데이터 변경·복원/장애 주입은 하지 않는다.

## 구현

- docs/operations/incident-recovery.md: Kafka disk/AZ와 노드 장애 구분, PVC/slot/offset/checkpoint 보존, RDS 별도 복원과 Airflow 이력 대조, 원본별 복구 한계.
- readiness.py: 도쿄·계정·실제 EKS endpoint를 대조한 읽기 전용 점검. Pod Ready·실제 Kafka PVC df·Prometheus·RDS 백업 설정/기존 CloudWatch disk/WAL·S3 3개 trade prefix 도착을 확인한다. 권한/지표/스캔 누락은 UNKNOWN이며 입력 없는 S3는 INFO다. 업무 DAG 성공은 자동 확인하지 않아 UNKNOWN으로 남긴다.
- 기존 Prometheus에 missing CDC/task metric 및 reload failure 3개 경보 추가. 5분 부재 경보와 정상/순간 scrape 실패를 가짜 시계열로 검증한다. 현재 자원과 외부 알림 보류는 유지한다.

## 초기 읽기 확인

기존 Kafka/Connect/Airflow/Prometheus/Grafana Pod Ready, Kafka 실제 PVC 사용률 9%, CDC connected=1, 비정상 Connect task 0, firing 경보 0을 확인했다. RDS available·백업 보관 7일 및 LatestRestorableTime 존재, 여유 약 18.25GB, instance 수준 WAL lag 약 61.6MB를 확인했다. 값은 점검 시점 관측이며 복원 성공·지속 정상 보장이 아니다. 상세 보고서는 Git 제외 worktree .cache에 보관한다.

## 완료 확인

- [x] 읽기 점검 판정 단위 검사 5개, Helm 경계, Prometheus 설정/10개 규칙 문법과 가짜 시계열 6개 시나리오 통과.
- [x] 실제 release values 보존·렌더 diff 검토 후 기존 모니터링 경보만 반영 및 상태 확인.
- [x] 코드·검증/적용 결과 로컬 보관. 원격 push/PR/승인/머지는 이번 요청에 포함하지 않음.

## 작업 결과

기존 cq-monitoring Helm revision 1→2 deployed. 실제 release values와 manifest를 비공개 보존하고 후보의 모든 객체를 대조했다. 변경은 monitoring-prometheus ConfigMap의 rules.yml 및 monitoring Deployment 3개의 checksum/config뿐이었다. 이미지·자원·권한·NodePool·PVC·Service와 자원 개수 22개는 유지하고 서버 dry-run 후 --atomic --wait로 적용했다. Recreate로 Prometheus/Grafana/Metrics Server가 잠시 중단됐다.

사후 확인: 규칙 10개 로딩·모두 health=ok·firing 0, monitoring Pod 3개 Ready. 노드 UID 및 api/kafka/airflow/argocd의 Pod 이름/UID가 사전과 동일하다. 사후 비교 helper가 JSON 저장 배열과 Python tuple의 자료형 차이로 한 번 실패했으며 실제 자원 변경은 없었다. 비교 형식만 수정하고 재배포 없이 읽기 재검증했다.

promtool의 read-only 컨테이너는 테스트용 TSDB가 /tmp를 필요로 해 초기 시계열 시험이 실패했다. 루트 파일시스템은 read-only를 유지하고 /tmp에만 128MiB tmpfs를 제공해 로컬/CI를 수정한 뒤 모두 통과했다.

S3 주문/주문상품/결제 prefix는 초기 추가 점검에서 모두 약 10분 전 도착 객체를 확인했고 목록 조회는 완전했다. 생성기 가동 여부를 단정하지 않아 INFO로 표시한다. AirflowBusinessRuns는 미연결 UNKNOWN이며 점검 도구 exit 2는 이 누락을 드러낸다. 실제 PITR 복원·Kafka 데이터 백업 생성/복원·HA 전환·외부 알림·업무 DAG 실행은 수행하지 않았다.

상세 값/manifest/plan은 원래 workspace .cache/incident-alert-* 및 이 worktree .cache/readiness-*.json에만 보관한다. 이번 범위에서 백업 보관 설정을 바꾸거나 새 상시 과금 리소스를 만들지 않았다. 다음 단계는 외부 통보 여부와 수동 점검의 정기화·Airflow 업무 실행 감시, 별도 복원 리허설을 결정하는 것이다.

## 2차 작업 — 승인된 이메일 장애 알림 (2026-10-23)

사용자가 기존 수신 주소로 이메일 연결을 명시 승인하고, PR #82 우선 리뷰 후 작업 재개를 요청했다. 이번 승인 범위의 SNS/경보/전달 역할과 Helm 연결을 적용했다. 이전 보류 중인 operations-alerts/Budget 브랜치를 활성화하지 않고 infrastructure-alerts라는 독립 state key를 쓴다. PR #84가 반영된 최신 main 473303a를 먼저 로컬 브랜치에 통합했다.

- 새 Terraform 모듈/스택: 도쿄 SNS topic·제한된 topic policy·비공개 이메일 구독, RDS 표준 CloudWatch 경보 5개, SNS publish만 가능한 Alertmanager 역할/Pod Identity. 계획은 11 create / 0 update / 0 delete였고 그대로 적용했다. DB/업무 데이터·노드·예산·CloudWatch Logs 변경은 없다.
- Helm: 선택적 Alertmanager v0.34.1 digest, 기존 API 노드 25m/64Mi 예약(상한 100m/128Mi), 내부 서비스와 설정·전용 SA만 추가. 공식 amtool 설정 검사 통과. Kubernetes API 권한은 없고 Pod Identity가 투영하는 AWS 토큰만 쓴다.
- 실제 기존 API 노드의 전체 namespace Pod 요청량 대조 결과 배포 전 CPU 705m·메모리 약 1394Mi 여유를 확인했다. 최초 조회 helper의 namespace 범위를 모든 namespace로 고친 뒤 재검증한 값이다.
- 실제 Helm values/manifest를 보존해 새 객체 4개 및 기존 Prometheus alerting 설정, monitoring 3개 Deployment checksum만 달라지는 것을 확인했다. 서버 dry-run 후 atomic Helm revision 2→3 deployed. 노드 UID 및 api/kafka/airflow/argocd Pod UID는 적용 전후 동일했다.
- Terraform fmt/validate·새 모듈 mock plan 1개·Helm 기본/선택 경계·공식 Alertmanager amtool·기존 readiness 판정 테스트 5개 통과. Mock의 계산된 SNS ARN을 plan 시점에 고정하도록 고쳐 권한 단언을 검증했다.
- SNS 확인 메일을 요청했으며 이메일 구독 확인은 수신자가 직접 한다. PendingConfirmation 상태와 실제 메일 수신 성공을 구분한다.

RDS 경보는 EKS 밖에서 평가되지만 Kafka/CDC 전달기는 모니터링과 같은 API 노드에 있다. 노드 자체 장애에 대한 독립 감시는 미연결이다. S3 입력 도착·업무 DAG 성공은 상시 수집/이메일 범위에 추가하지 않았다. Alertmanager emptyDir 재시작 시 silence/중복 방지 정보가 사라질 수 있다. 새 지속 비용은 표준 CloudWatch 경보 5개와 SNS 사용량이며 노드 추가 비용은 없다.

개인 이메일과 실제 plan/manifest/report는 Git 제외 파일에만 보관한다. push·PR·승인·머지는 별도 요청 전까지 하지 않는다.

### 2차 적용 결과

Alertmanager Pod Ready·Pod Identity 투영·Prometheus 알림 대상 1개와 경보 10개 건강 상태를 확인했다. RDS CloudWatch 경보 5개 모두 OK다. 합성 InfrastructureEmailDeliveryTest는 SNS Publish 1회 성공/실패 0회를 확인한 뒤 종료했다. 첫 시험은 Kubernetes 서비스 프록시 POST의 Content-Type이 맞지 않아 415로 거절됐고 경보가 생성되지 않았다. 해당 helper만 JSON HTTP 요청 및 임시 localhost 포트포워딩으로 바꿔 재검증했으며 종료 시 생성한 포트포워딩만 닫았다. 업무 데이터나 실제 장애를 만들지 않았다.

검증 시 SNS confirmed=0/pending=1이었다. 실제 메일 수신은 사용자가 확인 메일 링크를 누른 뒤 별도로 확인해야 한다. 자동 복구·정합성 판정·S3 도착/Airflow 업무 성공 상시 감시·독립 모니터링 heartbeat·복원 리허설은 후속이다.

최종 읽기 재확인에서는 confirmed=1/pending=0으로 전환되어 이메일 구독 활성화를 확인했다. Terraform 사후 계획은 변경 없음, 실행 중 Prometheus 설정의 공식 promtool 문법 검사 통과, 첫 합성 경보가 더 이상 활성 상태가 아님을 확인했다. 메일함의 실제 수신 여부는 직접 읽지 않는다.

이메일 활성화 후 별도 InfrastructureEmailConfirmedDeliveryTest도 SNS 전송 성공을 확인하고 종료했다. 누적 전송 2회/실패 0회다. 전달 경로 시험용 정상 복귀 메일도 뒤따를 수 있으며 실제 업무 장애가 아니다. CI mock suite 안전성 검사(15 suite/78 plan run 정의)와 workflow YAML 읽기 검사도 통과했다. 전체 78개 회귀를 다시 실행한 것은 아니며 이번 신규 모듈 mock 1개만 실제 실행했다.
