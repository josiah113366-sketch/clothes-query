# 2026-10-24 남은 실행 연결 순차 확인

상태: 실행 가능한 인프라 적용·검증 완료, 업무 명세/입력 의존 항목 대기
브랜치: infra/applied-state-sync, 소스 main 4d80c76(#95)

## 1. 노드 통합 이후 안정성

공용 노드를 합친 뒤 약 1시간 이상 지난 시점에도 API medium 1대·공용 large 1대가 Ready, Spark 노드는 0대다. 상시 Pod 재시작은 모두 0회이며 원본 Kafka 브로커도 재시작하지 않았다. 재확인 시 공용 CPU 18~32%, 메모리 약 74%였고 추가 예약 축소·노드 변경은 하지 않았다. 이 수치는 단기 재확인이며 연속적인 최대 부하 실측이 아니다.

기존 읽기 전용 운영 점검에서 Kafka 디스크 12%, CDC 연결 정상, 비정상 Connect Task 0개, firing Prometheus 경보 0개를 확인했다. RDS available, 백업 보존 7일, 사용 가능한 저장 공간 약 17GiB, OldestReplicationSlotLag 약 55MiB로 설정한 192MiB 경고 기준 아래였다. 복구 시험을 수행했다는 뜻은 아니다. 점검기의 일반 AirflowBusinessRuns 항목은 UNKNOWN을 반환하므로 별도 작업 이력 조회로 판정 성공을 확인했다.

## 2. #95 카탈로그 실제 반영

현재 Glue와 최신 DDL을 비교한 뒤 payment_events에 cdc_op/source_ts_ms/rule_version, malformed_events에 record_key/source_ts_ms 총 5컬럼을 추가했다. 기존 컬럼 타입과 순서가 예상과 다르면 중단하도록 대조했고, 표 삭제·재생성 없이 ADD COLUMNS만 사용했다. 각 표의 위치·파티션·projection 설정은 유지했다.

payment_states → payment_conflicts → payment_attempts → malformed_messages 순서로 main SQL을 Athena에 반영했다. 기존 테이블·뷰 정의는 Git 제외 영역에 백업했다. 첫 ADD COLUMNS 뒤 Athena가 자동 변경한 transient_lastDdlTime/last_modified_time/last_modified_by 메타데이터 때문에 보존 검사가 중단돼 이를 확인한 후 재개했다. 저장 위치·파티션·실제 projection 속성 검사는 유지했으며 이미 추가한 컬럼은 건너뛰었다.

로컬 SQL·DDL·payment_states 회귀 40개, Athena의 네 뷰 조회, 실제 detection-job Pod Identity로 네 뷰 조회를 통과했다. 배포는 00:07 KST에 끝났고, 이후 자연 예약 실행 00:10·00:15 success와 S3 작업 로그 저장도 확인했다. 더미 결제·원장 데이터는 넣지 않았다.

## 3. 조사·승인 연결

실제 ECR 조사 이미지와 investigation-agent ServiceAccount의 별도 일회용 Pod에서 모듈 로딩·STS 신원·Athena 장부/조사표 조회·업무 코드의 find_pending 조회를 확인했다. 현재 대기 사건 0건이다. Bedrock 실제 Converse 자체는 앞서 성공했지만, 이번에 모델 호출·리포트/실행 기록 쓰기·조사 DAG 활성화는 하지 않았다. 업무 사건→모델→리포트 전체 검증은 남는다.

실제 Dashboard Pod에서 기존 approval-dashboard 역할, REAL Athena 읽기, 모델 레지스트리 읽기, Airflow 인증 HTTP 201을 재확인했다. 후보와 요청은 각 0건이다. 기존 후보 DAG ID gold_b_reprocess/silver_gold_a_reprocess는 계속 HTTP 404다. 최종 업무 DAG ID와 입력·완료 기록을 담당자가 확정해야 하며, generic batch DAG와 자동으로 같은 계약이라고 간주하지 않는다. 승인·재처리 쓰기나 DAG 실행은 하지 않았다.

생성한 검증 Pod 2개는 UID·전용 label을 대조해 해당 Pod만 정리했다. 원래 paused인 조사 DAG는 그대로 유지했다.

## 4. 적재·Spark·SageMaker의 대기 이유

- Gold B 원장은 bronze_lag_snapshots만 Parquet 290개, 최신 00:10:03 KST 저장과 Athena 읽기를 확인했다. payment_events/topic_messages/malformed_events는 여전히 Parquet 0개다. 수집기는 v2 커넥터·그룹을 지정하지만 상시 Spark 적재와는 별도다.
- Gold B 상시 Spark의 최종 digest·실행 명령·checkpoint·Driver/Executor 자원 요구량은 아직 미수신이다. 기본 Spark/Python 버전이나 전용 노드 한도를 임의로 바꾸지 않았다. Silver·Gold A 첫 실행 성공과 Gold B 상시 실행 준비 완료를 혼동하지 않는다.
- Silver·Gold A의 Glue 공개·R6용 표/완료 시각·동일 실행 선택 규칙은 담당 명세가 필요하다. 미확정 스키마를 만들어 연결하지 않았다.
- SageMaker 최신 실패 Job(review-score-20261023-171118)은 패키지 실행 전 S3 입력 다운로드 단계에서 실패했다. 실제 입력 URI에 버킷 이름이 두 번 들어가며 현재 허용한 Silver prefix 밖이었다. run_processing_job.py의 --input-key는 버킷명이나 s3:// 주소가 아닌 객체 키를 받는다. 담당자의 제출 인자를 확인해야 한다.
- 현재 SSM의 입력은 silver/reviews/이며 그 prefix의 GetObject는 허용, 기존 잘못된 경로는 차단이다. 선택한 릴리스 manifest 형식·가중치 파일 이름/크기·score_batch.py/requirements.txt 존재는 확인했지만, Silver 입력 객체는 0개다. 가중치/후기 원문을 다운로드하지 않았고 새 GPU Job은 시작하지 않았다. 입력 변환·파일 형식은 업무 담당과 대조해야 한다.

## 팀원에게 받을 정보

| 담당 | 필요한 정보 |
|---|---|
| Gold B 상시 적재 | 최종 ECR digest, 실행 명령·환경변수, checkpoint prefix, Driver/Executor CPU·메모리, 실행 ServiceAccount |
| 판정·조사 | 실제 조사 검증 사건·기대 결과와 리포트 저장 확인 기준. 현재 대기 0건이므로 검증 사건을 임의 생성하지 않음 |
| 재처리 | 최종 DAG ID, 요청 JSON 계약, 작성 태스크/ServiceAccount, 완료 이벤트(source·step·범위) |
| Silver·Gold A/R6 | Glue 표·스키마·파티션, 완료 실행 공개 방식, completed_at·R6 조회 계약 |
| 후기 점수화 | 허용된 Silver 입력 객체 키·파일 형식·기대 건수, 선택 릴리스, 제출 명령의 --input-key 확인 |

위 정보가 도착하면 해당 연결부터 순차 진행한다. Kafka v2 Sink 정지→R3 실제 탐지 시험, 업무 재처리, GPU Job과 신규 상시 Spark 비용은 이번 확인에서 임의 실행하지 않았다. push·PR·승인·머지도 수행하지 않았다.
