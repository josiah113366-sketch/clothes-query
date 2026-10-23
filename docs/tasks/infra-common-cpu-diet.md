# 공용 노드 CPU 예약 축소

상태: CPU 예약 축소·공용 노드 통합 및 검증 완료 (2026-10-23, 원격 공유 전)
브랜치: infra/common-cpu-diet

## 목적과 범위

공용 t3a.large 한 대의 allocatable CPU는 1,780m인데 상시 Pod requests 합계가 1,900m였다. 당시 실제 사용량보다 예약량이 한 대 용량을 넘는 것이 두 대 유지의 근거였다. 실제 관측에서 Kafka/Connect와 관리 도구 CPU는 낮았으나 Airflow DAG processor는 순간 260m, Java 관리 프로세스의 메모리는 requests 근처여서 코어 서비스와 메모리는 줄이지 않았다.

| 대상 | 기존 CPU requests | 변경 |
|---|---:|---:|
| Strimzi cluster operator | 200m | 100m |
| Topic operator | 100m | 50m |
| User operator | 100m | 50m |
| Kafka exporter | 100m | 25m |
| Kafka UI | 100m | 25m |
| Dashboard | 250m | 100m |

상시 합계는 1,900m→1,400m(500m, 약 26.3% 감소)다. 기존 250m 판정/조사 Pod 한 개를 더하면 1,650m로 1,780m 안에 들어간다. 현재 Airflow의 작업 동시성 및 작은 개발 부하 기준이며, 수동 Pod나 병렬 작업을 추가하면 다시 증설할 수 있다. 메모리 requests/limits, 모든 CPU limits, broker 500m/1536Mi, Connect 250m/1Gi, Airflow 자원은 유지했다. CPU requests 감소는 CPU 상한을 낮춘 것이 아니며 경쟁 시 보장받는 비율이 작아진다.

## 적용 안전장치

단일 broker의 기존 PDB는 minAvailable=0으로 자발적 eviction을 허용했다. CRD의 지원 필드를 확인하고 single-node 프로필의 maxUnavailable=0을 먼저 적용해 생성 PDB의 minAvailable=1/disruptionsAllowed=0을 검증했다. 이 보호는 자발적인 노드 통합만 막으며 하드웨어 장애나 강제 종료에 대한 HA가 아니다. 이후 Kafka 노드 계획 정비 시 보호 해제와 중단 영향을 명시적으로 검토해야 한다. standard 프로필 기본값은 1로 유지했다.

작업 중에만 공용 NodePool disruption budget을 0으로 묶고, 적용 후 원래 budget 1로 복원했다. compute 한도·Spark 풀·노드 타입은 바꾸지 않았다. Helm에 저장된 과거 보관 기간이 실환경과 달랐으므로 실제 7일 값을 보존해 새 Helm 입력에 반영했다. 큰 millisecond 숫자가 과학 표기 float로 나오지 않도록 브로커·토픽 렌더를 정수로 고정했다. 실제 broker/Connect/NodePool/Topic/User spec을 비교해 의도하지 않은 변경이 없는지 검증했다.

현재 Helm values를 보존한 렌더 비교 후 strimzi와 cq-kafka를 순차 upgrade했다. atomic/wait를 사용했고 별도 dashboard CPU patch는 계정·환경변수·이미지를 보존했다. 대시보드 선언에는 먼저 적용한 approval-dashboard/Secret 연결을 유지하므로 해당 연결 브랜치와 후속 공유 때 중복 없이 통합한다. 운영·카탈로그 연결의 다른 미게시 브랜치를 되돌리지 않는다.

## 확인 결과

Helm lint, standard/single-node/CDC/Sink/pipeline/metrics 렌더, 고정 Strimzi CRD, 기존 거부 입력 35개와 저장소/운영자 검사가 통과했다. 단일 broker PDB 보호 회귀 검사를 추가했다. 관리 Deployment 4개와 dashboard 재배포 후 Ready를 확인했다. broker UID/restartCount 불변, broker config·KafkaNodePool 자원/저장소·Connect spec 불변을 적용 직후 대조했다. 기존 Kafka·S3 데이터·업무 계정·보관 기간을 줄이지 않았다.

자동 통합 시 broker 노드는 보호하며 다른 노드의 Connect·Airflow UI·관리 Pod는 이동/재시작할 수 있다. 이 작업을 무중단 보장으로 표현하지 않는다. 실제 노드 수·서비스 회복·판정 예약 실행 결과는 이어서 기록한다. 원격 push·PR·승인·머지는 별도 요청 없이 하지 않는다.

## 작업 결과

- 공용 상시 CPU requests는 실제 1,400m, 메모리는 5,504Mi다. 관리 Deployment와 dashboard 모두 Ready이며 broker UID와 재시작 횟수는 유지됐다. CDC source와 Bronze Sink 두 개 모두 RUNNING이다.
- 적용 이후 판정 예약 실행은 21:45~22:05 KST 연속 성공했고, 최신 로그의 S3 저장도 확인했다. 대시보드 approval-dashboard 실행 신원과 기존 환경변수 연결도 유지됐다.
- 최초 약 18분 관찰 후에도 공용 노드는 두 대였다. 이 시점에는 API 한 대를 포함해 총 세 대였으며 Spark 노드는 없었다. 이후 아래 사용자 승인 순차 통합으로 공용 노드 한 대를 종료했다.
- 공용 자동 통합의 consolidateAfter는 기존 10분 그대로다. 제거 대상 노드에 판정 Pod가 5분마다 배치·종료되는 이벤트를 확인했다. Karpenter는 Pod 추가·제거 시 대기 시간을 초기화하므로 이 주기와 대기 시간 조합이 통합을 지연시키는 것으로 판단한다. 예약량만으로 통합을 보장하지 않는다. [공식 동작 설명](https://karpenter.sh/v1.15/concepts/disruption/)
- 다음 단계는 공용 통합 대기 시간 조정과 이동 중 Connect·Airflow 가용성 검토다. 이번에는 NodePool 대기 시간·한도·노드 타입을 변경하거나 노드를 강제로 삭제하지 않았다. Kafka PDB 보호는 유지한다. CPU와 메모리를 더 줄이기 전에는 지속 사용량과 피크를 측정한다.

## 사용자 승인 후 순차 통합

사용자가 짧은 중단을 감수하는 통합을 승인했다. 자동 통합 대기 시간이나 용량 한도를 바꾸는 대신 Kafka 브로커가 없는 공용 노드의 기존 Pod를 순서대로 이동한다. 원래 판정·조사 DAG의 pause 상태를 저장하고 활성 판정 예약만 일시 정지한 뒤, 실행 중인 작업이 없는 것을 확인한다. 이동 대상 노드를 cordon하고, Entity Operator → Dashboard → Airflow DAG processor → API server → Kafka Connect 순서로 UID 조건을 둔 Eviction API를 사용한다. 각 대체 Pod가 Kafka 브로커 노드에서 Ready인 것을 확인한 다음 다음 Pod를 이동한다.

이동 동안 자동 disruption budget만 잠시 0으로 두고 종료 시 원래 1로 복원한다. 단일 브로커 PDB는 유지하며 매 단계 broker UID·재시작 횟수를 대조한다. Connect 복구와 전체 커넥터 RUNNING을 확인하고, 대상 노드가 완전히 빈 것을 확인한 뒤 해당 NodeClaim만 정상 종료한다. 강제 삭제·직접 EC2 종료·PVC 삭제·전체 drain을 사용하지 않는다. 기존 활성 판정 예약은 복원하고, 원래 paused였던 조사 DAG는 켜지 않는다.

### 통합 결과

- 22:56:29 KST에 공용 한 대의 EC2 terminated와 총 노드 두 대를 확인했다. 현재 API t3a.medium 한 대, 공용 t3a.large 한 대, Spark 노드 0대다. 용량 한도와 자동 증설 기능은 유지하므로 이후 부하에 따라 다시 늘 수 있다.
- Kafka 브로커의 UID와 재시작 횟수 0은 그대로다. 다른 공용 노드의 다섯 Pod만 순차 재생성했고 최종 모든 Pod Ready, 재시작 횟수 0을 확인했다. Connect REST API에서 CDC·기존 Bronze Sink·v2 Sink와 각 Task 모두 RUNNING을 확인했다. 새 업무 데이터 주입 시험은 하지 않았다.
- 판정 예약을 복원했고 22:50·22:55 예약 실행 success와 S3 로그 저장을 확인했다. 조사 DAG는 원래 paused 상태를 유지했다. 이동 중 판정 예약을 잠시 멈췄으므로 모든 5분 슬롯이 실행됐다고 표현하지 않는다.
- 새 Dashboard Pod에서 실제 Pod Identity, REAL Athena 읽기, 모델 레지스트리 읽기, Airflow 토큰 인증 HTTP 201을 확인했다. 재처리 DAG 두 개의 기존 404는 그대로이며 승인·재처리 실행은 하지 않았다.
- 통합 직후 공용 노드 실제 CPU 428m(24%), 메모리 4,948Mi(70%)를 확인했다. 상시 예약은 1,400m/5,504Mi다. Connect 시작 중 CPU 1,874m, Airflow API 초기화 중 일시 네트워크·probe 경고가 관측됐지만 최종 정상 복구됐다. 이 값은 단기 관측이며 장기 최대 부하 검증이 아니다.
- 커넥터 상태 조회 중 로컬→Kubernetes API 일시 시간초과가 발생해 첫 종료 시도를 보류하고 예약·disruption budget·cordon을 복원했다. 실제 REST와 상태를 재확인한 뒤 다시 cordon했다. 사이에 들어온 판정 Pod도 종료될 때까지 기다려 완전히 빈 노드만 정상 종료했다. 최종 disruption budget=1, consolidateAfter=10m, Kafka PDB 보호를 유지했다.
- 노드의 실제 종료로 t3a.large 한 대의 실행 비용이 줄었다. 정확한 금액은 별도 비용 조회 없이 산정하지 않는다. 이 변경은 로컬 기록만 남기고 push·PR·승인·머지는 하지 않았다.
