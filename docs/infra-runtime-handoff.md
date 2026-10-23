# 팀원에게 전달할 실행 연결 현황

2026-10-23 순차 복구·연결 및 공용 노드 통합 결과. 아래는 전달용 초안이며 외부 메시지는 보내지 않았다. 최신 main #95의 원장 추가 컬럼·payment_states와 의존 뷰 갱신은 기존 뷰 배포와 별도이며 이번 Git 정리에서 적용하지 않았다.

현재 총 노드는 API t3a.medium 1대와 공용 t3a.large 1대다. Spark 전용 풀은 활성화됐고 실행이 없으면 노드는 0대다. 실제 적용 후속은 infra/applied-state-sync에 통합했으며 아직 원격 push·PR·머지는 하지 않았다.

## 판정·조사 담당자

18:05 판정 실패는 이미지 문제가 아니라 gold_b.payment_attempts 뷰 누락이었습니다. 기존 조회 뷰 3개를 배포했고 23:00~23:25 예약 실행도 6회 연속 성공했습니다. Airflow S3 로그 권한도 복구해 관찰 계정에서 과거 로그를 읽을 수 있습니다. 조사 계정은 확정 JP Haiku 프로필로 실제 Converse HTTP 200까지 확인했습니다. 업무 입력을 읽고 조사 리포트를 저장하는 전체 DAG 검증과 새 #95 정의 배포는 별도입니다. 원장은 bronze_lag_snapshots만 실제 Parquet과 Athena 조회를 확인했고 나머지 세 원장은 데이터가 없었습니다.

## 대시보드 담당자

기존 대시보드를 dashboard/approval-dashboard 계정과 clothes-query-dev-dashboard workgroup에 연결했습니다. 승인 Backend는 REAL이며 후보·요청 조회, 모델 패치노트 S3 읽기, Airflow 인증을 실제 Pod에서 확인했습니다. 이미지·사용자 계정 파일은 변경하지 않았습니다.

AIRFLOW_API_URL=http://airflow-api-server.airflow.svc.cluster.local:8080 이고 기존 Secret dashboard/airflow-api-client의 username/password를 AIRFLOW_API_USER/PASSWORD로 참조합니다. 비밀값은 별도 전달하지 않습니다. 아직 gold_b_reprocess와 silver_gold_a_reprocess는 Airflow 조회에서 404라, 승인→재처리 전체 검증은 DAG 등록·계약 확정 뒤 진행해야 합니다. 이번 인프라 검증에서는 승인·재처리 기록을 쓰거나 DAG를 실행하지 않았습니다.

## Silver·Gold A 담당자

전용 NodePool 연결 후 실행하신 trade-v2-eks-20261023-b0185ff는 Driver/Executor 세 개 모두 exit=0이며, S3 Silver·Gold A manifest/completed는 PASS였습니다. coverage_status는 UNVERIFIED라 이력 범위 완전성과 추가 업무 사례는 계속 확인 부탁드립니다. 전체 Pod 로그는 airflow-logs/infra-spark-validation/<run_id>/에 보존하고 완료 Pod만 정리했습니다. 20:20 KST에 자동 종료로 Spark 노드 0대/EC2 terminated를 확인했고 결과 데이터와 NodePool은 유지했습니다. Glue 공개·R6 계약 및 재처리 DAG의 최종 ID/입력/완료 조건이 정해지면 연결하겠습니다.

## Gold B 상시 적재 담당자

Bronze v2 지연 수집기는 이미 60초마다 운영 중이고, Gold B 조회 뷰도 배포했습니다. 상시 Spark 적재는 별도입니다. 기본 Spark 4.2.0/Python 3.10.12 환경에 맞춘 최종 업무 이미지 digest, 실행 명령·환경변수, checkpoint prefix, Driver/Executor 자원을 전달 부탁드립니다. Silver·Gold A 배치와 한 대에서 동시에 돌릴지 여부는 이 자원 요구량을 보고 맞추겠습니다.
