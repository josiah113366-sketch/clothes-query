# 인프라 연결과 남은 작업

기준: 2026-10-24 KST, origin/main 4d80c76(#95 포함) 및 후속 순차 적용·검증. 배포 완료·업무 검증 성공·Git 반영 완료는 별개다. 8개 미게시 후속을 infra/applied-state-sync에 통합했고, 이어서 #95 컬럼·뷰를 실제 적용했다. 원본 브랜치와 root의 중지된 Gold B 이미지 실험은 보존한다. [후속 검증과 입력 대기 목록](operations/runtime-verification-20261024.md)을 따른다.

현재 노드는 API t3a.medium 1대와 공용 t3a.large 1대, 총 2대다. 사용자 승인으로 공용 2→1 통합을 완료했고 빈 노드의 EC2 terminated까지 확인했다. Kafka 브로커 UID·재시작 횟수는 유지됐으며 모든 상시 Pod와 커넥터는 정상이다. 공용 CPU 예약은 1,400m, 메모리 예약은 5,504Mi이며 통합 직후 실제 메모리는 약 70%였다. 노드 용량 한도와 자동 증설은 유지하므로 항상 두 대로 고정된 것은 아니다. Spark 풀은 활성화돼 있으나 현재 Spark 노드는 0대다.

## 지금 확인된 상태

| 구간 | 현재 상태 | 남은 것 |
|---|---|---|
| RDS → Kafka → S3 Bronze | cdc-source, 기존 Sink, v2 Sink 모두 RUNNING | v2 소비 경로와 기존 Sink 종료 시점은 데이터 담당 합의 |
| Kafka 보관 | 7일 설정 적용, #86 머지 | 20GiB 용량과 유입량 감시; 유입량에 무관한 7일 보관 보장은 아님 |
| Bronze v2 지연 수집기 | Running, 실제 Pod의 커넥터·그룹 모두 v2, 23:26 S3 저장·Athena 조회 재확인 | 장기 신선도 감시, 인증서 갱신 후 복사/재시작, v2 정지→R3 실제 시험은 별도 |
| Silver·Gold A Spark | Driver 1·Executor 2 종료 코드 0, Silver/Gold A manifest·완료 기록 PASS, 실제 출력 존재 | 로그 보존·완료 Pod 정리·자동 축소로 Spark 노드 0대/EC2 terminated 확인. coverage_status UNVERIFIED 및 추가 업무 사례는 담당자 확인 |
| Gold B 상시 적재 Spark | #92로 실행 코드·형식 검사기 main 도착 | 최종 실행 이미지·실행 계약·checkpoint·실행 신원·상시 자원 몫 확인 후 배포 |
| 판정 | #95 컬럼 5개·뷰 4개 반영, 실제 판정 역할 조회 통과, 배포 후 00:10/00:15 예약 실행 success | Gold B 상시 적재 데이터·업무 규칙 검증 |
| 조사 | JP Haiku 호출 성공 이력, 실제 이미지/역할의 모듈 로딩·Athena·대기 조회 통과, 대기 0건 | 검증 사건과 기대 결과를 받은 뒤 DAG→모델→리포트 저장 검증 |
| 승인 화면 | approval-dashboard·전용 workgroup·기존 Secret 연결, REAL backend 조회·패치노트 S3 읽기·Airflow 인증 통과 | gold_b_reprocess/silver_gold_a_reprocess가 Airflow에서 404. 업무 DAG 등록·계약 필요 |
| SageMaker 모델 | 릴리스 manifest·가중치 목록/크기·실행 코드 확인, Silver 읽기 허용·입력 객체 0개 | 최신 실패는 중복 버킷명/허용 범위 밖 입력. 올바른 Silver 객체 키·형식 수신 후 새 Job 검증 |

## 우선순위와 담당

팀원 정보 없이 가능한 운영 준비 네 가지는 완료했다. [한 명령 전체 점검](../infra/platform/monitoring/READINESS.md), [장애 대응 안내](operations/incident-recovery.md), [Git 공유 초안](operations/infrastructure-share-review.md), [팀원 전달문](operations/team-requests-20261024.md)을 마련했다. 새 상시 서비스·자동 복구·Git 원격 작업은 추가하지 않았다.

1. **로컬 통합·검증 완료 — 인프라: Git과 적용 상태 정리.** 설치된 운영 도구·데이터 실행 기반·노드 축소 후속을 한 브랜치로 취합한다. #73/#74는 이전 공유 초안이며 자동으로 갱신·닫거나 머지하지 않는다. 검증 결과는 [통합 작업 기록](tasks/infra-applied-state-sync.md)에 남긴다.
2. **완료 — 인프라: Airflow 로그 접근 복구.** 로그 역할·정책·association 6개를 복구하고 API/scheduler를 순차 재시작했다. 과거 로그 42개를 보존했으며 observer 로그 API HTTP 200과 새 scheduler의 S3 로그 쓰기를 확인했다. main 설정은 원래 존재했고 실환경만 누락돼 있었다. 제거 원인은 단정하지 않는다.
3. **완료 — 인프라: Gold B 조회 뷰 배포.** 기존 세 뷰 배포 후 #95의 원장 컬럼 5개와 payment_states 포함 네 뷰까지 반영했다. 실제 detection-job SA 조회와 뒤이은 00:10 판정 예약 실행 성공을 확인했다. 더미 업무 행은 만들지 않았다.
4. **완료 — 인프라: 승인 연결.** 실제 Deployment를 approval-dashboard·승인 전용 workgroup·AWS_REGION/DEFAULT_REGION·기존 airflow-api-client Secret의 username/password로 연결했다. 모델 registry GetObject/제한 목록 조회만 추가했고 권한 경계 7개를 검증했다. 후보/요청 실제 조회 및 Airflow 인증 성공, 이미지·계정 파일 불변을 확인했다. 사람 계정·화면 로직은 앱 담당이다.
5. **첫 실행·자동 축소 확인 — Silver·Gold A 담당 + 인프라.** 실행 trade-v2-eks-20261023-b0185ff의 Driver/Executor exit=0과 Silver·Gold A S3 manifest·완료 기록 PASS를 확인했다. coverage_status는 UNVERIFIED이므로 업무 범위·금액 등 추가 사례 검증은 담당자가 확인한다. 전체 Pod 로그를 S3에 보존하고 완료 Pod만 정리했다. 20:20:10 KST에 Spark 노드 0대/EC2 terminated를 확인했다. 수동 노드 삭제 없이 전용 풀을 유지했다.
6. **명세 대기 — Gold B 담당 + 인프라: 상시 적재 연결.** 사용자 확인 결과 최종 이미지 digest·실행 명령·checkpoint·Driver/Executor 자원 설정은 아직 미수신이다. 임의로 정해 배포하지 않는다. collector는 이미 별도 일반 Python Pod이며 이 상시 Spark와 다르다.
7. **연결 일부 완료 — 판정·조사 담당 + 인프라: 실제 업무 검증.** 판정은 최신 뷰 반영 뒤에도 예약 실행 성공, 조사는 실제 역할/이미지의 모듈 로딩·Athena·대기 조회 통과와 기존 JP Haiku Converse 성공 이력이 있다. 대기 사건은 0건으로 조사 DAG의 업무 입력→모델→리포트 저장은 검증 사건을 받아야 한다. 원래 paused 상태는 유지했다.
8. **재처리 담당 + 인프라: 승인 → Airflow → 재처리 → 완료 → 재판정.** 재처리 DAG ID·입력·완료 이벤트와 권한을 실제 코드에 맞춰 대조한다. Silver 공개/R6는 #87의 완료 목록·completed_at·Glue 공개 계약 확정/구현이 남아 있다.

## Spark 자원 교통정리

전용 풀은 t3a.large, 한 대분 2CPU/8GiB, WhenEmpty/10분 정리다. Silver·Gold A 검증에서 1대가 실제 생성됐고 완료 Pod 정리 후 자동 종료로 다시 0대가 됐다. Gold A 배치와 Gold B 상시 Spark를 한 대에서 동시에 수용할 수 있다고 검증한 상태는 아니다. Gold B 요구량을 받은 뒤 동시 실행 또는 대기를 결정한다. Gold B가 상시 실행되면 최소 Driver/Executor가 남아 노드도 상시 비용이 발생할 수 있다.

기본 Spark 4.2.0 / Python 3.10.12는 유지한다. 별도로 중지한 Gold B 이미지 실험을 적용된 환경으로 취급하지 않는다. 공용·API 노드 변경이나 두 번째 Spark 노드 증설은 이번 연결 범위가 아니다.

## Git 정리

2026-10-24 확인한 열린 PR: #97(재판정 실행 상한), #96(채점 스크립트), #87(자원/공개 계약), #90(앱의 7일 기본값), #85(규칙 문서), draft #73(운영 도구), draft #74(데이터 실행 기반). #89·#92·#93·#94·#95는 main 반영된 상태다. 새 #96/#97의 상세 리뷰·승인·배포는 이번 작업에서 수행하지 않았다.

미게시 적용 후속 silver-gold-a-connections, agent-bedrock-catalog, grafana-plugin-recovery, bronze-v2-lag-collector, spark-nodepool-enable, airflow-log-access-restore, dashboard-runtime-connect, common-cpu-diet는 infra/applied-state-sync 한 브랜치에 통합했다. 원본 브랜치는 보존했다. 기존 #73/#74와 중복되므로 이후 공유 시 이 통합 브랜치를 기준으로 정리한다. 사용자 요청 없이 push/PR/승인/머지하거나 기존 PR을 닫지 않는다.

**즉시 주의:** 이 통합 브랜치의 compute auto tfvars는 실제 활성 상태에 맞춰 enabled=true다. main에는 아직 false가 남으므로 반영 전 이전 설정으로 compute apply하지 않는다. 일부 bindings만 있는 오래된 local var-file로 전체 map을 덮어쓰지 않는다. 개인 이메일은 infrastructure-alerts의 Git 제외 입력을 사용하며 Git에는 수신 주소를 넣지 않는다.

## Gold B 데이터와 #95 후속 배포

23:26 확인에서 gold_b/bronze_lag_snapshots에 Parquet 246개가 있고 최신 파티션 Athena 조회가 성공했다. payment_events/topic_messages/malformed_events에는 Parquet이 없었다. 따라서 판정 DAG 성공만으로 Gold B 상시 적재나 업무 규칙 검증 완료를 주장하지 않는다.

#95는 2026-10-24 순차 후속에서 실제 반영했다. payment_events의 cdc_op/source_ts_ms/rule_version, malformed_events의 record_key/source_ts_ms만 추가했고 payment_states→payment_conflicts→payment_attempts→malformed_messages를 갱신했다. 현재 Glue 컬럼·위치·파티션·projection을 대조했으며 SQL·DDL 회귀 40개와 실제 판정 역할 조회가 통과했다. 앞선 Git 통합 시점의 미배포 기록은 이 후속 결과로 갱신한다. 원장 데이터는 00:10 재확인에서도 지연 수집기만 있고 나머지 세 원장은 비어 있었다.

## 보류

Argo CD의 앱별 자동 배포 규칙, Kafka 다중 broker/고가용성 확대, 추가 Spark 용량, 무차별 캐시/Docker 정리. Grafana·Argo CD 설치와 실제 자동 CD 연결은 다르다. 캐시 후보는 감사 기록만 있으며 사용자 승인 없이 삭제하지 않는다. root 작업 폴더의 미커밋 Gold B 이미지 실험도 보존한다.
