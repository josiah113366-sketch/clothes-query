# 실제 배포·Git 코드 대조 및 Grafana lag 점검

상태: 읽기 전용 1차 점검 완료, 인프라 변경·머지 없음

## 범위

2026-10-22 사용자 요청으로 최신 main과 배포된 인프라의 차이를 확인하고, Grafana Kafka consumer lag의 15분 톱니 모양을 조사했다. Tokyo/account 827913617635만 조회했다. main 기준은 `783fa84`이며 기존 Spark 작업은 `infra/spark-runtime-prep`의 `1bc9459`에 보존했다.

## 코드와 배포 대조

| 구성 | 확인한 실제 상태 | main과 차이 / 보관 브랜치 |
|---|---|---|
| 모니터링 | Prometheus·Grafana·Metrics Server 각각 1/1 Ready, 이미지 digest가 준비 코드와 일치, 기존 api 노드 사용 | main에 monitoring 디렉터리 없음. `infra/monitoring-baseline` `c76809a`에 코드 보관 |
| Argo CD | controller·server·repo-server·Redis 각각 Ready. ApplicationSet controller는 의도한 replicas=0. Argo/Redis digest가 준비 코드와 일치 | main에 argocd 디렉터리 없음. `infra/argocd-runtime` `6f84450`에 코드 보관 |
| Airflow | 본체 3개 Ready. 실제 GitDagBundle은 main의 `infra/platform/airflow/dags`, refresh 60초 | main의 values는 ConfigMap DAG 마운트 방식. Git bundle과 대시보드 인증 연결은 `infra/agent-runtime-connections` `8492873`·`444418c`에 보관 |
| Gold B 카탈로그 | 기존 DB·원장 테이블 등록은 별도 브랜치에서 수행한 이력 있음. 이번 점검에서 Glue API는 재조회하지 않음 | main에 gold-b-catalog 모듈/스택 없음. `infra/gold-b-catalog` `7499681` 보관 |
| Spark | 합성 시험 성공 후 임시 리소스 정리 기록 있음. 현재 조회 노드는 api medium·compute large 2대 | 상시 배포 비활성. 준비·시험 기록·업무 연결 변수는 `infra/spark-runtime-prep` 보관 |

코드가 main에 없다는 사실만으로 실행 중인 별도 Helm release가 자동 삭제되는 것은 아니다. 다만 main만으로 전체 환경을 재현할 수 없고, **현재 main의 이전 Airflow values로 upgrade하면 DAG 공급 설정을 되돌릴 위험**이 있다. 브랜치를 일괄 병합하거나 실제 Helm/Terraform 설정을 변경하지 않았다.

Airflow 3의 실제 설정 키는 `dag_processor.dag_bundle_config_list`다. `dag_bundle_config` 또는 해당 이름의 환경 변수만 검색해 bundle이 없다고 판단하면 잘못된 결과가 나온다. 실제 ConfigMap의 올바른 키를 확인해 Git 공급 상태를 검증했다. `airflow-infra-dags` ConfigMap이 남아 있다는 것만으로 현재 사용 중이라고 판단하지 않았다.

Airflow 3개 Deployment에는 공용 노드 hostname `i-0f22eae851d5a3035` 고정도 남아 있다. 해당 노드 교체 시 재배치가 막힐 수 있으므로 향후 공용 노드 변경/교체 전에 해제 계획이 필요하다. 이번 점검에서 변경하지 않았다.

## Grafana 톱니 모양의 원인과 증거

패널 쿼리는 `sum by (topic, consumergroup) (kafka_consumergroup_lag)`다. 대상 clickstream 시리즈의 group은 `connect-bronze-s3-sink`다. 최신 Kafka offset과 consumer group의 committed offset 사이 차이를 보여주므로 이미 읽어서 Sink가 처리 중인 데이터도 포함할 수 있다. '읽기 중단 건수', '메모리에 있는 건수', '누락 건수'와 동일한 지표가 아니다.

확인한 S3 Sink 설정:

- `flush.size=10000`: 파일별 건수 기준.
- `rotate.schedule.interval.ms=900000`: 15분 벽시계 주기.
- 토픽: clickstream/members-events/orders/order-items/payments.
- 파티셔너: TimeBasedPartitioner, UTC, `year/month/day` 경로.

최근 90분 기록에서 clickstream lag가 16:15, 16:30, 16:45, 17:00 KST마다 약 29,700~30,300에서 약 1,900~2,600으로 감소했다. S3 목록에서도 17:00:01~04 KST에 다섯 토픽 모두 새 Bronze 객체가 저장됐다. clickstream은 16:57~58에도 건수 조건으로 생성된 객체가 있어 15분마다만 쓰는 것은 아니다. S3 객체 내용·모든 offset의 연속성·중복/누락은 검사하지 않았다.

현재 cdc-source·bronze-s3-sink 및 각 task는 RUNNING, Prometheus scrape target 5개는 모두 up=1이었다. 반복되는 offset 확정 주기와 그래프가 일치하며, 조회 범위에서 누적 적체 증가나 연결 장애의 근거는 발견하지 못했다. 패널만으로 S3 적재 완료를 보장하지 않으므로 제목의 설명은 유지한다.

공식 동작 근거: [Confluent S3 Sink 설정](https://docs.confluent.io/kafka-connectors/s3-sink/current/configuration_options.html), [S3 Sink 시간 회전](https://docs.confluent.io/kafka-connectors/s3-sink/current/index.html).

## 다음 순서

2단계 후속 점검 완료: Airflow scheduler의 실제 CLI에서 DAG 목록과 import error를 조회했다. Git bundle의 설치 확인용 DAG 2개가 인식되고 모두 paused였으며 import error는 0건이었다. DAG processor의 tracking_repo HEAD가 main 783fa84와 일치했고 신규 DAG 기본 일시정지도 true였다. 현재 공급 절차를 infra/platform/airflow/DAG_DELIVERY.md에 정리했다. 업무 DAG를 실행하거나 Git/Helm 공급 설정을 변경하지 않았다. 다음은 3단계 RDS slot/WAL·Kafka PVC 여유 점검이다.

1. 운영 중인 미머지 코드의 의존성과 최신 main 차이를 정리해 개별 검토한다. 자동 머지하지 않는다.
2. 팀원에게 DAG 공급 경로·main 반영·60초 갱신과 실제 DAG 인식 확인 절차를 전달한다. Silver·Gold A의 업무 DAG 위치는 담당자 입력 후 확정한다.
3. 데이터 흐름 종합 점검은 RDS slot/WAL·Kafka PVC 여유·실제 전달 범위를 추가 확인한다. 이번에 확인한 것은 connector 상태·lag/offset·S3 객체 갱신이며 전체 end-to-end 또는 장애 복구 검증은 아니다.

## 작업 결과

읽기 전용 조회와 문서 작성만 수행했다. Terraform/Helm apply·커넥터 설정·Grafana 패널·업무 데이터·IAM을 변경하지 않았다. 새 클라우드 리소스나 테스트 데이터를 만들지 않았다. 상세 조회 결과는 Git 제외 `.cache/infra-live-code-audit.private.json`, `.cache/grafana-lag-audit-summary.json`, `.cache/s3-lag-freshness.json`에 보관한다.
