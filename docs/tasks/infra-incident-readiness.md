# Kafka·CDC·RDS 복구 준비와 기존 경보 보강

상태: 1차 완료(복구 절차·수동 점검·경보 반영, 실제 복원/외부 통보 제외) · 브랜치: `infra/incident-readiness` · 기준 main: `fbc6108`

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
