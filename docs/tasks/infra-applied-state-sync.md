# 적용된 인프라 후속 통합

상태: 통합·검증 완료 — 사용자 요청으로 Gold B 연결 기반을 추가하고 브랜치 공유
브랜치: infra/applied-state-sync
최초 기준: 2026-10-23 origin/main 4d80c76 (#95 포함). 현재 통합 기준: 2026-10-24 origin/main 85600ca (#100 포함).

## 목적과 범위

실제 환경에 적용된 후속이 여러 로컬 브랜치에 나뉘어 있어, 오래된 main 설정으로 apply할 때 Spark 풀·실행 권한·관리 도구 설정을 되돌릴 수 있었다. 사용자 요청에 따라 최신 main에서 통합 브랜치를 만들고 아래 여덟 후속을 원본 커밋 이력과 함께 순차 병합했다. 최초 범위는 Git 공유 준비였고, 이후 사용자가 CI 제외 가능한 작업과 push를 요청해 Gold B 실행 기반을 추가 적용했다. 업무 잡은 시작하지 않는다.

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

Git 통합 시점에는 #95의 원장 컬럼·payment_states가 미배포였고, 기존 뷰 성공과 최신 SQL 적용을 구분했다. 이어진 2026-10-24 사용자 요청으로 아래 순차 후속에서 실제 반영했다. 팀원의 업무 SQL 자체는 변경하지 않았다.

Gold B 상시 Spark의 최종 이미지·checkpoint·자원, 조사 업무 전체 검증, 재처리 DAG 계약, Glue 공개/R6 계약은 기존 대기 상태를 유지한다. 캐시·브랜치 삭제도 수행하지 않았다.

## 2026-10-24 운영 도구·안내 정리

사용자 요청으로 팀원 정보 없이 가능한 네 작업을 순차 완료했다. 기존 readiness.py에 --pipeline/--format summary를 추가해 노드 요청량·실사용, Connector/Task, 수집기의 실제 v2 대상, Gold B 카탈로그·객체 최신성, Airflow 실행/paused/등록을 한 명령으로 확인한다. 조회 실패·미배포를 정상과 구분하고 원문 업무 행·Secret·task 로그는 보고서에 포함하지 않는다. 자동 배포나 정기 실행은 추가하지 않았다.

검사 15개가 통과했다. 실제 첫 실행은 OK 34/INFO 5/WAITING 6/UNKNOWN 0/WARN 0으로 현재 미연결·paused 상태와 일치했다. 두 번째 실행은 사용량 조회에서 UNKNOWN 1개를 반환했고 native 종료 코드 2를 확인했다. 이후 metrics API와 kubectl top 재조회는 정상이며 공용 메모리는 약 75%였다. 조회 실패를 정상으로 바꾸거나 최종 검증 전체가 항상 정상이라고 기록하지 않는다. 도쿄 버킷 확인, 다른 context에서 추가 점검 중단, 잘못된/오래된 지표·제한된 객체 조회의 UNKNOWN 유지, 빈 오류 원장 처리 등을 검증했다.

현재 구조에 맞춰 장애 대응의 첫 확인·복구 후 기준, PDB/7일 보관/이메일 한계와 v2/R3 확인 순서를 보완했다. Git 공유 문서에는 리뷰 묶음·검증·#73/#74 중복 처리안과 PR 제목/본문을 준비했다. 담당자별 전달문에는 인프라 담당이 연결할 내용과 업무 담당이 확정할 입력·스키마·기대 결과를 나눴다. 외부 메시지·push·PR·승인·머지는 하지 않았다. 원격 CI도 아직 실행 전이다.

## 기존 draft PR 보존 대조

2026-10-24 사용자가 이전 draft PR과 올릴 브랜치 수를 확인하도록 요청했다. #73의 원격 head는 통합에 포함됐지만 #74에는 아직 빠진 gold-b-catalog 독립 스택·DAG 공급/배치 검사·접근 테스트 등 26개 경로가 있었다. 기존 '8개 후속 통합'이 '#74의 모든 내용 보존'을 보장하지 않았으므로 이를 명시적으로 바로잡았다. 최신 main 6c00ddc(#98/#99 포함)을 먼저 병합한 뒤 원격 #74 head를 추가 병합했다.

Dashboard 모델 registry 읽기와 JP Haiku 활성 설정은 최신 적용값을 유지해 충돌을 해결했다. 기존 state/backend 주소를 보존했으며 gold-b-catalog/dashboard-access/gold-b-access plan은 모두 변경 없음이다. Terraform 23 roots validate·mock plan 97개, Airflow/Spark/모니터링 Python 검사 46개가 통과했다. 공유값 및 실제 비공개 Helm overlay를 렌더해 Deployment 3개·migration Job 1개가 개별 hostname 없이 공용 풀을 선택하고 새 노드/PVC가 없는 것을 확인했다. 배포는 하지 않았다.

원격 #73/#74와 원본 브랜치는 그대로 보존했다. 새로 올릴 대상은 infra/applied-state-sync 한 개이며, 이를 공유한 뒤 두 draft를 대체 초안으로 정리하는 방안을 문서에 남겼다. 기존 PR을 닫거나 head를 덮어쓰거나 push·PR·승인·머지는 실행하지 않았다.

## 작업 결과

2026-10-24 #102 생성 뒤 사용자가 CI 실패 두 건을 먼저 해결하도록 요청해 이전 제외 범위를 변경했다. dashboard lock에 공식 서명으로 확인한 AWS 6.70.0 Linux h1만 추가했고 버전·기존 해시는 유지했다. Debezium의 기존 pin은 공식 파일·SHA-512와 일치하므로 바꾸지 않았다. BuildKit 원격 ADD를 컨테이너 HTTPS 다운로드·동일 SHA-256 검증·3회 제한 재시도로 바꿨다. Linux readonly init/validate, 정상·일시 오류·연속 오류 차단 fixture, 실제 이미지 빌드를 확인했다. [복구 기록](../operations/ci-checksum-recovery.md)을 따르며 AWS apply·운영 이미지 교체·DAG 실행은 하지 않는다.

2026-10-24 사용자가 CI를 제외한 가능한 인프라 작업 후 push를 요청했다. #100이 머지된 최신 main을 통합했고 #101 앱 코드는 가져오지 않았다. Gold B 실행 기반 준비 도구와 좁은 권한 map을 추가했다. ECR gold-b 저장소 1개, IAM 역할·정책·Pod Identity 9개를 create-only 계획으로 적용했다. 기존 리소스 변경·삭제·교체는 없고 적용 뒤 두 스택 plan은 변경 없음이었다. Kubernetes 계정/RBAC/ConfigMap/KafkaUser/NetworkPolicy 14개와 TLS Secret 2개, Airflow gold_b_ledger 1슬롯 pool을 준비했다.

역할별 허용·차단 12개씩 총 36개와 association 일치를 검증했고, 새 TLS 사용자 2개로 실제 Kafka 업무 토픽 5개의 메타데이터 접속을 확인했다. 메시지 소비·offset commit은 없었다. 현재 Airflow 3.3.2의 실제 KPO로 보완한 DAG 2개의 파싱·Spark toleration 변환·paused 기본값을 확인했다. 기존 node/pipelines Pod UID가 유지됐고 업무 Pod·노드·DAG 실행은 추가하지 않았다. 기본 pool 128슬롯과 기존 판정 활성 상태는 유지했다.

Terraform 23 roots·22 mock suites/98 plan 통과, Gold B 기반 Python 7개·기존 Gold B 회귀 226개·Spark 25개·Airflow 6개 통과。 마지막 입력 생성기 변경 뒤에도 기반 7개를 재확인했다. 최종 이미지 digest·checkpoint가 미정이므로 null pending 파일만 생성하고 AIRFLOW_GOLD_B_RUNTIME/적재 실행 환경은 공급하지 않았다. 기존 Silver·Gold A 자원 값도 아직 변경하지 않았다. CI 실패 수정·새 PR·기존 PR 종료·승인·머지는 범위에서 제외했다. 실제 비밀 입력·state·plan·인증서는 Git 제외 경로에만 보존한다.

2026-10-24 사용자가 Gold B 적재를 시험하고 기존 Spark 배치와 한 노드를 공유할 수 있는지 확인하도록 요청했다. main Gold B 이미지를 팀 기본 4.2.0/Python 3.10 이미지로 로컬 빌드하고, 내부 Docker 네트워크에서 실제 Kafka 스트리밍과 Silver·Gold A 배치를 함께 실행했다. 원장 41,000건, 주문 200건·매출 2,360,000이 기대값과 일치했고 두 작업 exit 0·OOM 없음, 합산 메모리 표본 최고 약 2.55GiB였다. 시험 종료 감지 경쟁 조건은 원본 오류를 보존하고 독립 결과 검증 후 수정했다. EKS 자원 예약 후보와 검증 한계는 [공유 검토](../operations/spark-shared-capacity-check.md)에 남겼다. 시험 컨테이너·네트워크를 정리했고 AWS 배포 및 기존 Spark 설정 변경은 하지 않았다.

8개 적용 후속을 최신 main 기반 한 브랜치에 모았고 소스 원본과 검증 이력을 보존했다. 핵심 9개 스택의 plan이 실제 환경과 일치했고, 현재 노드 수·v2 수집기·Spark 성공 및 종료·새 #95 미배포 범위를 문서에서 구분했다. 원격 공유와 실제 후속 카탈로그 배포는 별도 요청을 받아 진행한다.

## 2026-10-24 순차 후속 실행

위 Git 정리 완료 뒤 사용자가 나머지 작업을 순차 진행하도록 요청했다. 통합 노드 상태·운영 지표를 재확인하고 #95를 별도로 실제 적용했다. 원장 누락 컬럼 5개만 추가하고 네 뷰를 순서대로 갱신했으며 저장 위치·파티션·projection은 유지했다. 관련 회귀 40개, 실제 판정 역할 조회, 배포 뒤 00:10 예약 실행 성공까지 확인했다. Git 정리 단계의 '미배포' 기록은 이 시점부터 완료로 갱신한다.

실제 조사 이미지/역할의 모듈 로딩·Athena·대기 조회도 통과했고 대기 사건은 0건이다. 승인/재처리 DAG 계약, Gold B 상시 Spark, Silver 공개/R6와 SageMaker 입력은 아직 팀원 의존이다. SageMaker 최신 실패는 잘못된 입력 URI의 다운로드 단계였으며 선택 릴리스와 정상 Silver 권한은 확인했다. 업무 코드·후기 원문·모델 가중치를 변경하지 않았다. 새 Spark/GPU 작업·승인·재처리·조사 업무 쓰기는 실행하지 않았다. 상세 결과는 [순차 검증 기록](../operations/runtime-verification-20261024.md)을 따른다.
