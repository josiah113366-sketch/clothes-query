# 인프라 연결과 남은 작업

기준: 2026-10-23, origin/main 044dae2 및 후속 순차 적용·실측. 배포 완료·업무 검증 성공·Git 반영 완료는 별개다. 이 문서는 기존 b0185ff 기준 작업 목록보다 최신이다. 로그 권한·조회 뷰·대시보드 연결을 적용했으며 기존 예약 실행과 팀원의 Spark 검증 결과를 관찰했다. 새 업무 실행·승인·재처리를 임의로 시작하지 않았다.

## 지금 확인된 상태

| 구간 | 현재 상태 | 남은 것 |
|---|---|---|
| RDS → Kafka → S3 Bronze | cdc-source, 기존 Sink, v2 Sink 모두 RUNNING | v2 소비 경로와 기존 Sink 종료 시점은 데이터 담당 합의 |
| Kafka 보관 | 7일 설정 적용, #86 머지 | 20GiB 용량과 유입량 감시; 유입량에 무관한 7일 보관 보장은 아님 |
| Bronze v2 지연 수집기 | pipelines/gold-b-lag-collector Running, 60초 간격 S3·Athena 2회 실측 성공 | 장기 신선도 감시, 인증서 갱신 후 복사/재시작 |
| Silver·Gold A Spark | Driver 1·Executor 2 종료 코드 0, Silver/Gold A manifest·완료 기록 PASS, 실제 출력 존재 | 로그 보존·완료 Pod 정리·자동 축소로 Spark 노드 0대/EC2 terminated 확인. coverage_status UNVERIFIED 및 추가 업무 사례는 담당자 확인 |
| Gold B 상시 적재 Spark | #92로 실행 코드·형식 검사기 main 도착 | 최종 실행 이미지·실행 계약·checkpoint·실행 신원·상시 자원 몫 확인 후 배포 |
| 판정 | 누락 뷰 3개 배포 후 19:55/20:00/20:05 예약 실행 3회 success; 로그 읽기·쓰기 복구 | 원장 데이터 정확성과 업무 규칙 검증은 별도 |
| 조사 | 실제 investigation-agent Pod의 JP Haiku Converse HTTP 200 확인 | 실제 업무 입력으로 조사 DAG→리포트 저장 검증 |
| 승인 화면 | approval-dashboard·전용 workgroup·기존 Secret 연결, REAL backend 조회·패치노트 S3 읽기·Airflow 인증 통과 | gold_b_reprocess/silver_gold_a_reprocess가 Airflow에서 404. 업무 DAG 등록·계약 필요 |
| SageMaker 모델 | 새 release/registry_prefix SSM 실제 적용 | 첫 실제 Job의 고정 패키지 설치·추론 검증, 대시보드 패치노트 읽기 연결 |

## 우선순위와 담당

1. **완료 — 인프라: Airflow 로그 접근 복구.** 로그 역할·정책·association 6개를 복구하고 API/scheduler를 순차 재시작했다. 과거 로그 42개를 보존했으며 observer 로그 API HTTP 200과 새 scheduler의 S3 로그 쓰기를 확인했다. main 설정은 원래 존재했고 실환경만 누락돼 있었다. 제거 원인은 단정하지 않는다.
2. **완료 — 인프라: Gold B 조회 뷰 배포.** 확정된 main SQL의 payment_conflicts→payment_attempts→malformed_messages를 생성했다. 실제 detection-job SA 조회와 뒤이은 판정 예약 실행 성공까지 확인했다. 더미 업무 행은 만들지 않았다.
3. **완료 — 인프라: 승인 연결.** 실제 Deployment를 approval-dashboard·승인 전용 workgroup·AWS_REGION/DEFAULT_REGION·기존 airflow-api-client Secret의 username/password로 연결했다. 모델 registry GetObject/제한 목록 조회만 추가했고 권한 경계 7개를 검증했다. 후보/요청 실제 조회 및 Airflow 인증 성공, 이미지·계정 파일 불변을 확인했다. 사람 계정·화면 로직은 앱 담당이다.
4. **첫 실행·자동 축소 확인 — Silver·Gold A 담당 + 인프라.** 실행 trade-v2-eks-20261023-b0185ff의 Driver/Executor exit=0과 Silver·Gold A S3 manifest·완료 기록 PASS를 확인했다. coverage_status는 UNVERIFIED이므로 업무 범위·금액 등 추가 사례 검증은 담당자가 확인한다. 전체 Pod 로그를 S3에 보존하고 완료 Pod만 정리했다. 20:20:10 KST에 Spark 노드 0대/EC2 terminated를 확인했다. 수동 노드 삭제 없이 전용 풀을 유지했다.
5. **명세 대기 — Gold B 담당 + 인프라: 상시 적재 연결.** 사용자 확인 결과 최종 이미지 digest·실행 명령·checkpoint·Driver/Executor 자원 설정은 아직 미수신이다. 임의로 정해 배포하지 않는다. collector는 이미 별도 일반 Python Pod이며 이 상시 Spark와 다르다.
6. **연결 일부 완료 — 판정·조사 담당 + 인프라: 실제 업무 검증.** 판정은 예약 실행 3회 성공, 조사는 실제 ServiceAccount의 JP Haiku Converse 1회 성공이다. 조사 DAG의 업무 입력→모델→리포트 저장과 품질/시나리오 검증은 남는다. DAG paused 상태를 임의 변경하지 않았다.
7. **재처리 담당 + 인프라: 승인 → Airflow → 재처리 → 완료 → 재판정.** 재처리 DAG ID·입력·완료 이벤트와 권한을 실제 코드에 맞춰 대조한다. Silver 공개/R6는 #87의 완료 목록·completed_at·Glue 공개 계약 확정/구현이 남아 있다.

## Spark 자원 교통정리

전용 풀은 t3a.large, 한 대분 2CPU/8GiB, WhenEmpty/10분 정리다. Silver·Gold A 검증에서 1대가 실제 생성됐고 완료 Pod 정리 후 자동 종료로 다시 0대가 됐다. Gold A 배치와 Gold B 상시 Spark를 한 대에서 동시에 수용할 수 있다고 검증한 상태는 아니다. Gold B 요구량을 받은 뒤 동시 실행 또는 대기를 결정한다. Gold B가 상시 실행되면 최소 Driver/Executor가 남아 노드도 상시 비용이 발생할 수 있다.

기본 Spark 4.2.0 / Python 3.10.12는 유지한다. 별도로 중지한 Gold B 이미지 실험을 적용된 환경으로 취급하지 않는다. 공용·API 노드 변경이나 두 번째 Spark 노드 증설은 이번 연결 범위가 아니다.

## Git 정리

열린 PR: #87(자원/공개 계약), #90(앱의 7일 기본값), #85(규칙 문서), draft #73(운영 도구), draft #74(데이터 실행 기반). #89·#92·#93·#94는 main 반영된 상태다. 각 PR의 상세 리뷰·승인은 별도다.

미게시 적용 후속은 silver-gold-a-connections, agent-bedrock-catalog, grafana-plugin-recovery, bronze-v2-lag-collector, spark-nodepool-enable, airflow-log-access-restore, dashboard-runtime-connect 브랜치에 있다. #73/#74 및 후속 PR로 중복 없이 묶을 수 있으나 사용자 요청 없이 push/PR/승인/머지하지 않는다.

**즉시 주의:** 실제 Spark 풀은 활성화됐지만 main의 compute auto tfvars는 아직 enabled=false다. 활성화 브랜치를 공유·반영하기 전까지 이전 설정으로 compute apply하지 않는다. Airflow 로그 연결은 복구됐고 workload-access post-plan은 무변경이다. 일부 bindings만 있는 오래된 local var-file로 전체 map을 덮어쓰지 않는다. dashboard-access 원본 state 코드도 복원·패치했으므로 공유 시 draft #74와 중복을 정리한다.

## 보류

Argo CD의 앱별 자동 배포 규칙, Kafka 다중 broker/고가용성 확대, 추가 Spark 용량, 무차별 캐시/Docker 정리. Grafana·Argo CD 설치와 실제 자동 CD 연결은 다르다. 캐시 후보는 감사 기록만 있으며 사용자 승인 없이 삭제하지 않는다. root 작업 폴더의 미커밋 Gold B 이미지 실험도 보존한다.
