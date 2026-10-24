# 개발 환경의 장애 대응·복구 절차

기준: 2026-10-24, 도쿄 / clothes-query-dev-eks. 현재 API medium 1대에 WAS·모니터링·Argo CD, 공용 large 1대에 단일 Kafka·Connect·Airflow·Dashboard가 있다. RDS는 Single-AZ이며 업무 DB와 airflow_meta를 함께 사용한다. Spark 전용 풀은 실행할 때 노드가 생기며 현재 0대다. HA 전환이나 실제 복원 리허설을 완료한 것으로 해석하지 않는다. 사고 중에는 데이터와 복제 위치를 먼저 보존하고 원인 확인 전 반복 재시작·삭제·재배포를 피한다.

## 한 번에 현재 상태 보기

```powershell
python -X utf8 infra/platform/monitoring/readiness.py --live --pipeline --format summary --output .cache/incident-status.json
```

WARN은 관측한 문제, UNKNOWN은 확인 실패, WAITING은 미연결·paused다. 전체가 정상이어도 이 도구는 데이터 계산 결과까지 증명하지 않는다. 보고서 파일과 실패 시각을 보존하고, 조회 실패만으로 서비스를 재시작하지 않는다. metrics 조회만 UNKNOWN이면 아래 읽기 명령으로 재확인한다.

```powershell
kubectl top nodes
kubectl get pods -A
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp
```

## 증상별 첫 확인과 복구 후 기준

| 증상 | 먼저 확인 | 복구 후 확인 |
|---|---|---|
| API·Grafana·Argo CD가 함께 안 보임 | API 노드 Ready·메모리·각 Pod와 Service. 공용 Kafka 노드와 구분 | 같은 URL 접속, API 오류/지연, Prometheus targets·경보 전달 |
| Kafka·Airflow·Connect가 함께 멈춤 | 공용 노드 상태, Kafka PVC/EBS attach, RDS 상태 | broker Ready→Connector/Task RUNNING→CDC connected→실제 Bronze 도착→다음 판정 성공 |
| v2 Bronze가 멈춤 | bronze-s3-sink-v2의 상태·Task·lag·권한/저장 오류, collector가 같은 v2를 보는지 | v2 Task RUNNING, committed offset 진행과 해당 S3 prefix 새 객체. Kafka lag 감소만으로 S3 보장하지 않음 |
| 판정만 실패 | Airflow task 로그, Pod 이벤트/이미지 종료 코드, Glue 뷰·Athena 권한 | 실제 판정 역할의 읽기와 다음 예약 실행 성공. 원장이 비면 업무 규칙 검증은 별도 |
| 조사/재처리가 대기 | paused 또는 DAG 미등록인지, 실행 명세/사건이 있는지 | 담당자가 정한 사건·요청으로 업무 결과 확인. 미연결을 서버 장애로 취급하지 않음 |
| SageMaker가 시작 전에 실패 | 입력 S3 URI, --input-key의 버킷 중복, 허용 Silver 경로·실제 객체 | 실행 요청 dry-run 대조 후 합의한 입력으로 검증. 권한을 Bronze 전체로 넓히지 않음 |

## 먼저 할 일

1. [읽기 전용 점검](../../infra/platform/monitoring/READINESS.md)을 실행한다. 발생 시각·영향 토픽/서비스·마지막 정상 S3 도착·실행 중 DAG/잡 범위를 기록한다. 지표 부재와 조회 권한 실패는 UNKNOWN이며 정상으로 처리하지 않는다.
2. 노드/Pod 장애인지, EBS/AZ 장애인지, RDS/CDC 장애인지 구분한다. Grafana가 안 보여도 Kafka가 죽었다고 단정하지 않는다. 모니터링과 WAS는 같은 API 노드를 공유한다.
3. 추가 쓰기가 손실 범위를 키우는 상황이면 해당 생성기/업무 잡의 일시정지를 담당자와 판단한다. 이 문서나 점검 도구는 자동 정지·재시작·failover를 실행하지 않는다.
4. PVC/PV/EBS·replication slot·Kafka offset·Spark checkpoint를 보존한다. 공유 계정이므로 대상 namespace·UID·계정·도쿄를 확인한다. 비밀번호·토큰·업무 행을 공용 로그나 Git에 복사하지 않는다.

## Kafka Pod 또는 공용 노드 장애

현재 Kafka는 broker/controller 1개와 AZ에 종속된 EBS PVC를 사용한다.

- Pod/노드 상태, PVC Bound 여부, 이벤트의 volume attach/mount 실패와 용량을 확인한다. 점검 도구의 df는 실제 PVC 데이터 mount만 읽으며 파일을 수정하지 않는다.
- 디스크가 살아 있으면 같은 AZ의 대체 노드에서 Strimzi가 기존 PVC를 다시 연결하는 경로를 확인한다. 새 노드를 만들 수 있는 NodePool 한도·AZ 용량·Pod 배치 조건도 확인한다.
- 이전 노드가 여전히 살아 있는지 확인하지 않고 EBS를 강제 분리하거나 강제 attach하지 않는다. Kafka CR·KafkaNodePool·PVC·PV를 삭제하거나 새 빈 디스크로 교체하지 않는다.
- 브로커 Ready 뒤 토픽/파티션·Connect task·CDC 연결과 offset, 실제 Bronze 도착 순으로 확인한다. 마지막 정상 시각 이후의 빠진 구간과 중복 가능성을 기록한다.
- 현재 single-node PDB maxUnavailable=0은 자발적 eviction을 막는 보호다. 노드/EBS/AZ 장애를 무중단으로 해결하는 기능은 아니다. PDB만 풀고 broker를 이동시키는 식으로 복구하지 않는다. 노드 정상화와 디스크 소유권 확인 후 배치·삭제 결정을 검토한다.
- 디스크 손실 또는 AZ 장애에서는 다른 Kafka 복제본이 없다. 노드 재생성만으로 복구되지 않는다. EBS snapshot이 있다면 생성 시각·정합성을 검토하고, 없다면 아래 원본별 재수집 범위를 합의한다. Kafka 실행 중 EBS snapshot을 단순 생성한 것을 완전한 정합성 백업으로 간주하지 않는다.

## CDC 끊김·WAL 증가

- 순서: RDS 연결 → Connect/task → Debezium connected 지표 → slot 상태/WAL 여유 → 토픽 유입 → Bronze 도착.
- 현재 설정의 max_slot_wal_keep_size는 256MiB다. 점검 도구의 기본 사전 경고는 instance 수준 OldestReplicationSlotLag 192MiB 이상이다. 실제 설정이 바뀌면 도구의 --wal-budget-mib도 맞춘다. 이 값은 특정 slot의 유효성이나 복구 가능 시간을 보장하지 않는다.
- 권한 있는 DB 세션에서 아래 읽기 전용 SQL로 실제 slot을 확인한다. 결과에 업무 데이터는 없지만 내부 식별자는 비공개 취급한다.

```sql
SHOW max_slot_wal_keep_size;
SELECT slot_name, slot_type, active, wal_status, safe_wal_size,
       restart_lsn, confirmed_flush_lsn,
       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_wal_bytes
FROM pg_replication_slots;
```

- active=false만 보고 slot을 삭제하지 않는다. wal_status=lost 또는 필요한 WAL 부재면 단순 재시작으로 이어 읽을 수 있다고 가정하지 않는다. 재스냅샷·누락 구간 대조·중복 처리를 CDC 담당자와 계획한다.
- slot 삭제/advance, 커넥터 삭제·재등록, offset 초기화, 토픽 삭제는 복구 전용 변경으로 별도 검토한다. 점검·재시작 명목으로 실행하지 않는다.

## RDS 장애·백업 복구

- 현재 DB는 Single-AZ, 자동 백업 보관 7일이다. 일회성 점검은 available·보관 설정·LatestRestorableTime·남은 공간만 확인하며 복원을 실행하지 않는다.
- 일시 장애는 AWS 상태/이벤트와 재접속을 확인한다. DB를 복원해야 하면 기존 DB를 덮어쓰지 않고 별도 식별자로 snapshot/PITR 복원을 계획한다. 복원에는 추가 DB 비용이 발생한다.
- 복원 후 보안 그룹·CA/SSL·DB/계정·RDS endpoint·Secrets 참조·CDC slot/커넥터 위치를 대조한다. 기존 업무 DB와 airflow_meta가 함께 영향받는 점을 고려한다.
- Airflow 메타DB의 복원 시점이 뒤로 돌아가면 외부에서 이미 끝난 작업과 이력이 어긋날 수 있다. 자동 일괄 재실행보다 run_id/request_id와 결과 manifest를 먼저 대조한다.
- 이번 단계에서는 실제 PITR 복원·장애 전환 시험을 하지 않았다. 자동 백업 설정이 있다는 것과 성공적으로 복원했다는 것은 구분한다.

## 데이터 종류별 복구 원본

| 데이터 | 재구성 후보 | 한계 |
|---|---|---|
| 주문·주문상품·결제·회원 CDC | 남은 Kafka/WAL, RDS snapshot/PITR, 이미 적재된 Bronze | 현재 RDS 행의 재스냅샷은 삭제/변경의 전체 과거 이력을 복원하지 않음 |
| 클릭 이벤트 | 이미 적재된 Bronze, 별도로 보존된 생성 원본이 있으면 해당 파일 | Kafka에만 있고 S3에 도착하지 않은 이벤트는 복구 원본이 없을 수 있음 |
| 리뷰 | 실제 리뷰 S3 원본·생성 원본 | 토픽이 비어 있거나 별도 경로일 수 있으므로 담당 경로를 먼저 확인 |
| Silver·Gold A·Gold B 원장 | 고정 Bronze/Kafka 입력, 실행 요청/manifest·코드·규칙 버전 | 입력 이력/참조 자료가 남아 있어야 동일 결과 재현 가능 |
| Spark Streaming 위치 | 확정된 S3 checkpoint | checkpoint 삭제·서로 다른 잡의 경로 공유를 피함. Gold B 업무 checkpoint 경로/복구는 아직 미검증 |

S3 마지막 도착 시각은 해당 prefix에 객체가 생겼다는 증거이며 전체 토픽의 무손실·정합성 증거가 아니다. Kafka retention 7일 설정도 디스크 손실 대비 백업이 아니며 20GiB에 언제나 7일치가 들어간다는 보장은 없다.

## v2 Sink 정지와 R3 확인

사건 대상은 bronze-s3-sink-v2다. collector의 실제 GOLD_B_SINK_CONNECTOR와 GOLD_B_SINK_GROUP은 각각 bronze-s3-sink-v2/connect-bronze-s3-sink-v2여야 한다. 정지 시험은 데이터 담당과 입력 발생·정지/복원 시각을 합의한 뒤 별도로 진행하며 이 안내나 점검은 커넥터를 멈추거나 재개하지 않는다.

현재 main의 R3는 connector_state 문자열 자체가 아니라 lag_sec 또는 측정 부재를 판정한다. 기본 지연 기준 1,200초, 측정 부재 3분과 5분 판정 주기를 구분한다. collector가 계속 기록하고 유입이 없으면 Sink 정지만으로 R3가 즉시 발생한다고 가정하지 않는다. 실제 적용 이미지/설정의 업무 기준은 담당자와 확인한다. 복원 시 offset을 초기화하지 않고 기존 위치에서 진행하는지 본다.

## Airflow·업무 실패

Pod Ready는 업무 DAG 성공을 뜻하지 않는다. UI/CLI에서 import error·scheduler heartbeat·실패/대기 task·마지막 성공과 task 로그를 확인한다. 재실행 전 기존 S3 결과·완료 manifest·재처리 이력과 대조한다. metadata DB를 지우거나 작업 상태를 일괄 success로 바꾸지 않는다. 판정·조사·Spark 업무 이미지는 각 소유자의 고정 digest와 실행 계약을 사용한다.

로그가 비어 있으면 앱 오류로 단정하지 않는다. scheduler의 airflow-logs/ 쓰기와 API의 읽기 Pod Identity, 실제 S3 로그 존재를 대조한다. Secret·비밀번호를 출력하지 않는다. 기존 workload-access의 전체 bindings와 최신 공유 설정을 보존해 plan을 확인하며 일부 map만 담긴 로컬 파일로 다른 역할을 지우지 않는다. #95 뷰는 이미 반영됐으므로 TABLE_NOT_FOUND가 나오면 대상 DB·workgroup·뷰·역할부터 다시 대조하고 표를 삭제/재생성하지 않는다.

복구 뒤에는 ① 서비스 정상 ② 데이터 흐름 재개 ③ 새 업무 실행 성공 ④ 중복/누락·완료 기록 대조를 각각 기록한다. 한 단계만 통과한 것을 전체 복구 완료로 표시하지 않는다.

## 아직 보호하지 못하는 것

- Kafka disk/AZ 손실의 자동 인계, RDS Multi-AZ 자동 전환, 노드 하나가 죽어도 계속 일하는 복제본은 이번 범위가 아니다.
- Alertmanager→SNS 이메일과 RDS CloudWatch 경보는 승인 후 연결했다. 수신 주소는 비공개이며 이메일 수신 확인과 마지막 전달 결과를 대조한다. Discord는 미연결이다. 모니터링 노드 자체가 죽으면 이 Prometheus도 경보를 평가·전달하지 못하며 EKS 밖 RDS 경보와 감시 범위가 다르다.
- Secret 원문을 파일로 내보내는 백업, 새로운 EBS snapshot 자동화, 유료 exporter·정기 점검 Pod를 추가하지 않는다. Secret 원본 저장소/접근 권한·복원 절차와 실제 backup restore는 후속 검증 대상이다.

공식 근거: [RDS WAL/디스크 지표](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-metrics.html), [EBS AZ 제한](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volumes.html), [RDS PITR](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIT.html).
