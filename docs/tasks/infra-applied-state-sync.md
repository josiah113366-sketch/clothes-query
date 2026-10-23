# 적용된 인프라 후속 통합

상태: 완료 — 로컬 통합·검증·커밋, 원격 공유 전
브랜치: infra/applied-state-sync
기준: 2026-10-23 origin/main 4d80c76 (#95 포함)

## 목적과 범위

실제 환경에 적용된 후속이 여러 로컬 브랜치에 나뉘어 있어, 오래된 main 설정으로 apply할 때 Spark 풀·실행 권한·관리 도구 설정을 되돌릴 수 있었다. 사용자 요청에 따라 최신 main에서 통합 브랜치를 만들고 아래 여덟 후속을 원본 커밋 이력과 함께 순차 병합했다. 새 AWS 배포나 업무 실행이 아니라 Git 공유 준비다.

| 원본 브랜치 | 포함 내용 |
|---|---|
| infra/grafana-plugin-recovery | 모니터링·Argo CD, 장애 복구 안내, 이메일 인프라 경보, Grafana 플러그인 복구 |
| infra/silver-gold-a-connections | Spark 기본 이미지 발행 정보, ECR push 권한, S3 endpoint, 거래 실행 역할·template |
| infra/agent-bedrock-catalog | JP Haiku 권한, 판정·조사 digest 설정과 Git DAG 연결 도구 |
| infra/bronze-v2-lag-collector | v2 수집기 이미지·렌더·역할·그룹 권한과 배포 기록 |
| infra/spark-nodepool-enable | 승인된 전용 풀 enabled=true, 첫 Spark 실행·자동 축소 기록 |
| infra/airflow-log-access-restore | 로그 권한 복구, 기존 조회 뷰 배포, 실제 Bedrock 연결 검증 기록 |
| infra/dashboard-runtime-connect | 기존 dashboard-access state 소스, 실제 실행 신원·Athena·Airflow·패치노트 연결 |
| infra/common-cpu-diet | CPU 예약 500m 축소, 단일 broker PDB 보호, 공용 노드 2→1 통합 기록 |

기존 draft #73/#74는 과거 공유 묶음이다. 이 통합 브랜치가 후속 전체를 포함하므로 이후 공유 때 중복 범위를 정리하되, 이번에는 기존 PR을 갱신·닫거나 승인·머지하지 않는다. 원본 여덟 브랜치·기타 보류 브랜치·root 미커밋 Gold B 이미지 실험은 그대로 보존했다.

## 충돌과 현재 배포값

충돌은 브랜치 대장, Kafka 보관 변경의 과거 작업 기록, 작업 목록 문서에서 해결했다. main의 Kafka 7일 보관·v2 소비자 그룹·UI/exporter 설정과 #95 업무 코드·DDL·SQL을 유지했다. Spark enabled=true, Dashboard approval-dashboard 및 기존 Secret 참조, Kafka PDB maxUnavailable=0과 낮춘 CPU 예약을 한 소스 트리로 모았다. state 주소·backend key를 바꾸지 않았다.

현재 총 노드는 API medium 1대와 공용 large 1대이며 Spark 노드는 0대다. Spark 풀은 활성 상태로 작업 시 노드를 생성한다. 용량 한도는 유지하며 고정 노드 수로 변경하지 않았다. 실제 Helm values, TLS 인증서, Secret 값, 개인 이메일·IP, state·plan은 Git에 추가하지 않는다. 경보 개인 입력은 Git 제외 파일이 필요하며 이를 공용 값으로 대체하지 않는다.

## 검증

- Windows Terraform 1.15.8: fmt -check, backend·클라우드 자격증명 없는 격리 환경에서 22 roots init/validate, 19 suites의 mock plan 93개 통과. provider 캐시와 공통 격리 data 디렉터리를 재사용해 실행 폴더별 provider 중복 복사를 줄였다.
- Python unittest: Spark 25, Airflow 6, v2 collector 4, monitoring 5, 검사 실행기 9개, 총 49개 통과.
- Kafka Helm lint 및 standard/single-node/CDC/Sink/pipeline/metrics 렌더, Strimzi 1.3.0 schema와 거부 입력 35개 검사 통과. main의 v2 권한과 브로커 보호를 함께 검증했다.
- Monitoring 22개 리소스 렌더, Argo CD 고정 chart checksum 및 42개 리소스 렌더 통과. Prometheus config 문법, 경보 규칙 10개 및 rule tests 통과. Docker는 시작하지 않았다.
- 실제 state 읽기 전용 plan: compute, ecr, network, spark-access, gold-b-access, bronze-lag-collector, dashboard-access, infrastructure-alerts, workload-access 모두 managed resource 변경 0개. 개인 입력과 plan JSON은 Git 제외 영역에만 저장했다. Terraform apply·state 이동·import는 실행하지 않았다.
- 업무 경로 pipelines/agent/api/simulator/review-simulator/connectors/db의 main 대비 diff 없음, Git diff 공백·충돌 표식 및 신규 비밀 파일 검사 수행. 원격 CI는 push하지 않아 실행하지 않았고, 로컬 통과를 원격/Linux CI 통과로 대신하지 않는다.

## 다음 작업과 경계

공유할 때는 이 브랜치와 [최신 작업 목록](../infra-work-queue.md)을 기준으로 검토한다. 아직 main에 반영 전이므로 main의 이전 compute 설정으로 apply하지 않는다. 별도 요청 전까지 push·PR 생성·승인·머지는 하지 않는다.

#95는 원장 컬럼과 payment_states 선행 뷰를 추가했다. 기존 뷰 3개 조회 및 판정 실행 성공이 최신 #95 카탈로그 배포 완료라는 뜻은 아니다. 추가 컬럼 대조·최신 뷰 갱신은 다음 별도 배포 작업으로 남긴다. 이번 통합으로 업무 SQL을 변경하거나 실환경 뷰를 교체하지 않았다.

Gold B 상시 Spark의 최종 이미지·checkpoint·자원, 조사 업무 전체 검증, 재처리 DAG 계약, Glue 공개/R6 계약은 기존 대기 상태를 유지한다. 캐시·브랜치 삭제도 수행하지 않았다.

## 작업 결과

8개 적용 후속을 최신 main 기반 한 브랜치에 모았고 소스 원본과 검증 이력을 보존했다. 핵심 9개 스택의 plan이 실제 환경과 일치했고, 현재 노드 수·v2 수집기·Spark 성공 및 종료·새 #95 미배포 범위를 문서에서 구분했다. 원격 공유와 실제 후속 카탈로그 배포는 별도 요청을 받아 진행한다.
