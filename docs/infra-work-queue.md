# 인프라 연결과 남은 작업

기준: 2026-10-23, origin/main 044dae2 및 실제 AWS/EKS 읽기 점검. 배포 완료·업무 검증 성공·Git 반영 완료는 별개다. 이 문서는 기존 b0185ff 기준 작업 목록보다 최신이며, 이 정리 과정에서는 업무 Job/DAG를 실행하거나 AWS 설정을 바꾸지 않았다.

## 지금 확인된 상태

| 구간 | 현재 상태 | 남은 것 |
|---|---|---|
| RDS → Kafka → S3 Bronze | cdc-source, 기존 Sink, v2 Sink 모두 RUNNING | v2 소비 경로와 기존 Sink 종료 시점은 데이터 담당 합의 |
| Kafka 보관 | 7일 설정 적용, #86 머지 | 20GiB 용량과 유입량 감시; 유입량에 무관한 7일 보관 보장은 아님 |
| Bronze v2 지연 수집기 | pipelines/gold-b-lag-collector Running, 60초 간격 S3·Athena 2회 실측 성공 | 장기 신선도 감시, 인증서 갱신 후 복사/재시작 |
| Silver·Gold A Spark | 기본 이미지/업무 이미지, 계정·권한·템플릿 준비; 전용 NodePool Ready | silver-gold-a-v2-b0185ff Job은 suspend=true, active=0, Spark 노드 0대. 수동 검증 재개·실측 |
| Gold B 상시 적재 Spark | #92로 실행 코드·형식 검사기 main 도착 | 최종 실행 이미지·실행 계약·checkpoint·실행 신원·상시 자원 몫 확인 후 배포 |
| 판정 | 실제 Pod 기동·이미지 실행 확인 | 18:05 두 시도 exit=1, Athena gold_b.payment_attempts 누락으로 실패 |
| 조사 | 이미지·DAG·Bedrock JP Haiku 역할 기반 준비 | 실제 업무 입력으로 모델 호출과 결과 저장 검증 |
| 승인 화면 | #94 이미지가 실제 배포됨; 내부 Airflow health HTTP 200 | 현재 default SA, 승인 환경변수 없음. approval-dashboard 역할 연결과 Secret/env 반영 |
| SageMaker 모델 | 새 release/registry_prefix SSM 실제 적용 | 첫 실제 Job의 고정 패키지 설치·추론 검증, 대시보드 패치노트 읽기 연결 |

## 우선순위와 담당

1. **인프라: Airflow 로그 접근 복구.** 현재 airflow namespace Pod Identity association 0개, API Pod의 S3 로그 읽기 NoCredentialsError 확인. 원래 로그 전용 역할/정책·state·Pod 상태를 대조한 뒤 복구한다. 역할이 있더라도 Pod 재생성·자격증명 주입까지 확인한다. 과거 18:05 로그는 scheduler 로컬에 있어 원인을 확인할 수 있었다.
2. **인프라 + Gold B 담당: 조회 뷰 배포.** Glue gold_b에 원장 등 8개 객체는 존재하나 payment_attempts가 없다. 필요한 뷰 정의와 의존 객체를 확인해 배포하고 실제 판정 SA에서 조회한다. #53의 판정/조사 표 생성 완료와 Gold B 전체 조회 객체 완료를 혼동하지 않는다.
3. **인프라 + 대시보드 담당: 승인 연결.** namespace dashboard / SA approval-dashboard 및 Pod Identity는 존재한다. AIRFLOW_API_URL은 http://airflow-api-server.airflow.svc.cluster.local:8080 이다. 기존 Secret dashboard/airflow-api-client의 username/password를 AIRFLOW_API_USER/PASSWORD로 연결한다. main #94의 주석 예시 dashboard-airflow/user와 실제 Secret 이름·키가 다르므로 그대로 사용하지 않는다. 승인 workgroup·AWS_REGION·SA·패치노트 GetObject 범위를 함께 확인한다. 사람 계정·화면 로직은 앱 담당이다.
4. **Silver·Gold A 담당 + 인프라: 첫 수동 검증.** 업무 이미지 b0185ff… / digest 241d5b96…를 ECR·Job과 대조했다. Job은 팀원이 일시정지했다. 재개 후 인프라는 노드 부팅·Driver/Executor·Pod Identity·S3 커미터·자원/정리를 보고, 팀원은 입력과 기대 건수·금액·품질 결과를 판정한다. 업무 성공은 아직 미검증이다.
5. **Gold B 담당 + 인프라: 상시 적재 연결.** 코드는 도착했으므로 존재하지 않는 코드 대기로 표시하지 않는다. 실제 사용할 이미지 digest·진입 인자·Kafka/S3/checkpoint·계정과 Driver/Executor 자원 계약을 확인한다. collector는 이미 별도 일반 Python Pod이며 이 상시 Spark와 다르다.
6. **판정·조사 담당 + 인프라: 실제 업무 검증.** 누락 뷰 해결 후 판정 성공, 조사 모델 호출/저장, 5분 주기 시간·자원 확인. 현재 판정은 팀원이 활성화했고 반복 실패 기록이 있으므로 paused/실행 0개라고 기록하지 않는다. 이 정리에서 DAG 상태를 임의 변경하지 않았다.
7. **재처리 담당 + 인프라: 승인 → Airflow → 재처리 → 완료 → 재판정.** 재처리 DAG ID·입력·완료 이벤트와 권한을 실제 코드에 맞춰 대조한다. Silver 공개/R6는 #87의 완료 목록·completed_at·Glue 공개 계약 확정/구현이 남아 있다.

## Spark 자원 교통정리

전용 풀은 t3a.large, 한 대분 2CPU/8GiB, WhenEmpty/10분 정리다. 고정 replicas가 없어 현재 0대다. Gold A 배치와 Gold B 상시 Spark를 한 대에서 동시에 수용할 수 있다고 검증한 상태는 아니다. 우선 Silver·Gold A 하나만 실측하고 Gold B 요구량과 비교해 동시 실행 또는 대기를 결정한다. Gold B가 상시 실행되면 최소 Driver/Executor가 남아 노드도 상시 비용이 발생할 수 있다.

기본 Spark 4.2.0 / Python 3.10.12는 유지한다. 별도로 중지한 Gold B 이미지 실험을 적용된 환경으로 취급하지 않는다. 공용·API 노드 변경이나 두 번째 Spark 노드 증설은 이번 연결 범위가 아니다.

## Git 정리

열린 PR: #87(자원/공개 계약), #90(앱의 7일 기본값), #85(규칙 문서), draft #73(운영 도구), draft #74(데이터 실행 기반). #89·#92·#93·#94는 main 반영된 상태다. 각 PR의 상세 리뷰·승인은 별도다.

미게시 적용 후속은 silver-gold-a-connections, agent-bedrock-catalog, grafana-plugin-recovery, bronze-v2-lag-collector, spark-nodepool-enable 브랜치에 있다. #73/#74 및 후속 PR로 중복 없이 묶을 수 있으나 사용자 요청 없이 push/PR/승인/머지하지 않는다.

**즉시 주의:** 실제 Spark 풀은 활성화됐지만 main의 compute auto tfvars는 아직 enabled=false다. 활성화 브랜치를 공유·반영하기 전까지 이전 설정으로 compute apply하지 않는다. 또한 Airflow 로그 연결이 실제로 사라져 있으므로 전체 workload-access를 오래된 로컬 설정으로 apply하지 않고 먼저 state/실환경을 대조한다.

## 보류

Argo CD의 앱별 자동 배포 규칙, Kafka 다중 broker/고가용성 확대, 추가 Spark 용량, 무차별 캐시/Docker 정리. Grafana·Argo CD 설치와 실제 자동 CD 연결은 다르다. 캐시 후보는 감사 기록만 있으며 사용자 승인 없이 삭제하지 않는다. root 작업 폴더의 미커밋 Gold B 이미지 실험도 보존한다.
