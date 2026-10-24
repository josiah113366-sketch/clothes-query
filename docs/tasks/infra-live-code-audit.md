# 실제 배포·Git 코드 대조 및 Grafana lag 점검

상태: 배포·Git 대조 / Airflow DAG 공급 / RDS·Kafka 용량의 1~3단계 읽기 전용 점검 완료, 인프라 변경·머지 없음

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

### 3단계: RDS slot/WAL·Kafka PVC 점검 완료 (2026-10-22 17:18~17:21 KST)

기존 Airflow DB 계정으로 read-only 트랜잭션을 열고 statement timeout 5초/lock timeout 2초에서 시스템 뷰만 조회했다. 세션은 rollback/close했고 업무 테이블·자격증명·권한을 변경하지 않았다. 새 Pod를 만들지 않고 기존 scheduler와 Kafka 컨테이너에서 조회했다.

| 항목 | 관측 결과 |
|---|---|
| RDS | available, db.t4g.small/PostgreSQL 16.15, 20GiB·자동 증가 최대 100GiB, 백업 7일 |
| 변경 대기 | PendingModifiedValues 없음, 파라미터 그룹 in-sync, 조회한 pg_settings pending_restart 모두 false |
| RDS 여유 공간 | 약 16.96GiB (CloudWatch 최신 표본 17:13 KST) |
| CPU | 최근 1시간 5분 평균 표본 약 6.5~7.3% |
| DB 연결 | CloudWatch 사용자 연결 21개. SQL pg_stat_activity 전체 30~32개는 내부 프로세스 포함. max_connections=181 |
| 복제 슬롯 | cdc_slot 한 개/설정 한도 5개. pgoutput·postgres DB, 모든 표본 active=true·wal_status=reserved |
| 슬롯 보존 WAL | 1.12MiB → 60.29MiB → 0.83MiB → 0.73MiB. 증가 후 다시 감소 |
| 소비 확인 위치 차이 | 마지막 표본 약 105KiB. 누적 정체 근거 없음 |
| Kafka | broker Running, 재시작 0, PVC Bound/20Gi |
| Kafka 파일시스템 | 실제 약 19.52GiB 중 약 0.83GiB 사용, 약 18.68GiB 여유, df 기준 5% |

WAL 생성량은 첫 약 43초 구간에서 약 1.39MiB/s였지만 뒤 구간은 훨씬 작았다. 부하에 따라 달라지는 짧은 표본이며 장기 지속 처리량이나 장애 허용 시간을 보장하지 않는다. max_slot_wal_keep_size=256MiB는 CDC 중단 시 WAL 보존을 제한하는 설정이며 고정 보존 시간이 아니다. 적용은 checkpoint와 관련되고 다른 WAL 보존 조건도 있으므로 256MiB에 도달하는 순간 슬롯이 삭제된다고 해석하지 않는다. 실제 max_wal_size=2048MiB, 조회된 safe_wal_size는 약 2GiB였으며, 전체 TransactionLogsDiskUsage 약 2.19GiB와 단일 슬롯이 붙잡은 WAL은 다른 지표다.

참고: [PostgreSQL 16 복제 슬롯 지표](https://www.postgresql.org/docs/16/view-pg-replication-slots.html), [WAL 보존 한도](https://www.postgresql.org/docs/16/runtime-config-replication.html).

추가 설정 차이: 공유·로컬 유효 입력 및 RDS 파라미터 그룹에는 max_wal_senders=10이지만 실제 엔진 값은 20이다. 2026-10-18 RDS 이벤트 두 건에서 복제에 맞지 않는 10을 20으로 자동 조정했다는 메시지를 확인했다. 사용자/동료가 변경한 것으로 단정하지 않는다. 이번에는 Terraform 입력·파라미터 그룹·DB를 변경하지 않았으며 향후 RDS 코드 정합성 검토 항목으로 남긴다.

이번 관측으로는 저장 공간 증설이나 긴급 재부팅이 필요한 징후가 없었다. 이전 CDC·S3 객체 갱신 확인과 합쳐 현재 연결 상태는 양호하지만, 메시지별 누락/중복·장기 72시간 보존·장애 복구·CDC 정지 시 허용 시간은 검증하지 않았다. 외부 알림 설정도 새로 추가하지 않았다.

상세 근거는 Git 제외 .cache/rds-kafka-capacity-audit.private.json, .cache/rds-capacity-followup.private.json, .cache/rds-adjustment-events.json에 보관한다. 요청한 1~3단계 읽기 전용 점검을 완료했다.

읽기 전용 조회와 문서 작성만 수행했다. Terraform/Helm apply·커넥터 설정·Grafana 패널·업무 데이터·IAM을 변경하지 않았다. 새 클라우드 리소스나 테스트 데이터를 만들지 않았다. 상세 조회 결과는 Git 제외 `.cache/infra-live-code-audit.private.json`, `.cache/grafana-lag-audit-summary.json`, `.cache/s3-lag-freshness.json`에 보관한다.
