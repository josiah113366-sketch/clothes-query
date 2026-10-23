# Kafka 7일 보관

상태: 적용 및 복구 검증 완료 · 독립 브랜치: `infra/kafka-retention-only`

2026-10-23 사용자가 7일 변경만 먼저 머지 가능한 형태로 분리하도록 요청했다. origin/main 083931f에서 기존 Kafka 커밋 60850a7만 가져왔다. docs/BRANCHES.md 충돌은 이 Kafka 브랜치 한 줄만 남겨 해결했으며, 인프라 알림·모니터링·Argo CD·Spark 변경은 포함하지 않는다. 아래 적용 결과는 앞서 실환경에 반영했던 작업 이력이고, 이번 분리 작업에서 클러스터를 재배포하지 않는다.

독립 브랜치에서 Helm lint, standard/single-node/CDC/Sink/pipeline/metrics 렌더, Strimzi 1.3.0 CRD 검사 및 잘못된 입력 35개 거부 검사가 통과했다. main 대비 변경은 Kafka 코드·설정·검사 7개와 작업/브랜치 문서 2개뿐이다. push·PR·머지는 아직 하지 않았다.

사용자가 2026-10-23 보관 기간을 72시간에서 1주일로 늘리도록 요청했다. 디스크는 20GiB로 유지한다. 변경 전 실제 Kafka PVC 사용률은 9%(약 1.75GiB)였으며 이것만으로 향후 7일분 용량을 보장하지 않는다.

## 범위

- 업무 토픽 clickstream, members-events, orders, order-items, payments 및 debezium-heartbeat.cdc의 retention.ms를 604800000으로 변경.
- 브로커에는 log.retention.ms=604800000만 전달한다. 프로필의 retentionHours=72는 retentionMs가 없는 경우에만 사용하는 비활성 fallback이며 두 alias를 동시에 렌더링하지 않는다. 기본 비활성 standard 프로필의 24시간 제안은 변경하지 않는다.
- Connect 내부 configs/offsets/status 토픽은 cleanup.policy=compact를 유지한다. 소비자 offset 보관 기간과 CDC slot/WAL 예산은 별도이며 변경하지 않는다.
- 기존 Helm release values와 전체 manifest를 대조해 Kafka CR 설정 한 개 및 KafkaTopic 6개의 보관 값만 바뀌는 것을 확인했다. 자원 생성/삭제, replica·image·ACL·Connect·PVC·NodePool 변경은 없다.
- 이미 삭제된 메시지는 복구되지 않는다. 세그먼트 단위 정리이며 디스크 부족·broker 장애까지 보관을 보장하는 설정은 아니다.

## 검증

- optional retentionMs를 schema에 추가하고 공식 Strimzi 1.3.0 CRD 검증, 기존 render/rejection 검사 모두 통과. 초기에 schema에 새 필드가 없어 lint가 거부됐고 추가 후 통과했다.
- 실제 Helm values 보존, 전체 manifest diff 7개만 허용, 서버 dry-run 통과.
- operator observedGeneration/Ready 및 Pod/PVC/node UID를 적용 후 확인한다. 업무 행·시험 메시지는 새로 쓰지 않는다.

## 작업 결과

최초 적용은 시간 단위 log.retention.hours=72를 유지하면서 밀리초 설정을 추가했으나 Strimzi 1.3.0이 두 alias의 차이를 계속 발견해 재생성을 반복했다. Kafka 자체의 dynamic 지원만으로 이 운영자 조합의 무중단 변경을 보장하지 못했다. 운영자 로그의 `log.retention.hours` SET/DELETE 및 재시작 원인과 이벤트를 확인했고, chart를 둘 중 하나만 전달하도록 수정한 뒤 legacy hours 하나만 제거하는 별도 manifest diff/서버 dry-run을 거쳐 적용했다. 롤백해 보관 기간을 다시 줄이거나 offset/slot/checkpoint를 초기화하지 않았다.

이 과정에서 브로커 Pod가 반복 재생성됐고 Connect의 liveness 실패로 재시작이 5회 발생했다. 업무 연결 중단을 유발한 이번 변경의 부작용이다. Kafka PVC와 노드 UID는 보존했고 데이터 삭제·신규 메시지 주입은 하지 않았다. 보존된 볼륨을 확인한 것이 모든 업무 이벤트의 무손실을 증명하는 것은 아니다.

수정 후 브로커 실행 설정 파일에 log.retention.ms=604800000만 존재하는 것을 확인했다. KafkaTopic 6개는 7일 값·observedGeneration/Ready를 확인했다. 시간/밀리초 alias를 함께 렌더링하지 않는 회귀 단언을 추가하고 Helm/Strimzi 검사를 다시 통과했다. CDC source와 Bronze S3 Sink의 connector/task가 모두 RUNNING으로 회복됐다. Kubernetes Ready 조건의 마지막 전환 시각과 UID를 대조해 최소 150초 이상 연속 준비 상태를 확인하고 최종 readiness 결과도 보관한다. 재기동 중 초기 readiness WARN/지표 UNKNOWN을 정상으로 숨기지 않았다.

읽기 관찰 helper가 NotReady→Ready 전환 시 안정 시작 시각을 초기화하지 않는 오류가 있어 local observer만 종료·수정했다. 최종 판정은 실제 Kubernetes Ready.lastTransitionTime 및 실행 설정·REST/지표의 별도 읽기로 확인한다. Kafka/Connect를 추가 재시작하지 않았다.

비공개 증거는 원래 workspace의 Git 제외 .cache/kafka-week-*에 보관한다. 별도 요청 전 push·PR·머지는 하지 않는다.

최종 결과: 두 Pod 연속 Ready 187초, 업무/heartbeat 6개 모두 7일, 브로커 실행 설정 확인, CDC/Sink connector/task 모두 RUNNING, PVC/node UID 보존. 디스크 사용률 10%. 최종 readiness WARN 없음, CDC/task 지표 모두 OK, 기존 미연결 AirflowBusinessRuns만 UNKNOWN이다. 기존 이벤트 정합성이나 PITR 복원까지 검증한 결과는 아니다.

[Kafka 4.3 브로커 설정](https://kafka.apache.org/43/configuration/broker-configs/)에서 log.retention.hours는 read-only, log.retention.ms는 cluster-wide dynamic이며 밀리초 설정이 우선함을 확인했다.
