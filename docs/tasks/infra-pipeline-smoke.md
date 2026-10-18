# 시험 데이터 경로 연결

상태: 실제 AWS 연결·시험 정리 완료 / 리뷰 대기 · 2026-10-18

## 요청과 범위

업무 테이블·제네레이터·Airflow가 미정이어도 숫자 시험 데이터를 RDS/PostgreSQL → Debezium → Kafka → S3로 전달하는 연결을 먼저 준비한다. 실제 AWS 적용과 로컬 S3 호환 API 검증을 구분한다. PR 승인·머지는 팀원이 한다.

## 작업 계획

1. 기존 local CDC/mTLS/재시작 검사를 재사용해 선택적 S3 Sink 검사를 추가.
2. Kafka Connect에 Sink용 명시적 topic/group 읽기 ACL을 선택적으로 지원.
3. 기존 Kafka/PVC·업무 데이터와 분리한 AWS 시험 설정·SQL·적용/종료 절차 준비.
4. 로컬 실제 송수신·저장, Helm/CRD, AWS plan 확인. 2026-10-18 사용자가 실제 AWS 적용·재부팅·시험 데이터 정리를 명시적으로 승인해 이번 시험에 한해 담당자 직접 apply 규칙의 예외로 실행했다.

## 완료 확인

- `python -X utf8 infra/platform/kafka/local-smoke/check.py --compact --s3`
- `python infra/platform/kafka/verify/check.py --helm .cache/helm/windows-amd64/helm.exe` (검증 venv 사용)
- 시험 overlay의 Helm 렌더 및 Connector 공식 CRD 검사.
- AWS plan 변경/삭제/교체 여부 확인, 승인 후 실제 전송과 시험 자원 정리 및 후속 무변경 plan 확인.

## 작업 결과

- 기존 CDC 검사를 선택적으로 확장해 S3 Sink 12.1.13과 Moto S3 fixture를 추가했다. 운영용 DB·업무 토픽·S3 경로 없이 숫자 데이터로 연결을 확인한다. 기본 실행은 기존 CDC-only 동작을 유지한다.
- Connect에 선택적 literal consumeTopics/consumerGroups ACL을 추가했다. 기본은 빈 배열이며 source-only 권한을 넓히지 않는다. undefined topic·group 누락·wildcard 입력을 거부한다.
- AWS용 시험 schema/전용 DB 역할/토픽·72시간/Connect·S3 prefix와 비활성 overlay, Connector CR, 초기화 SQL, 최소 S3 역할 및 적용/종료 절차를 준비했다. 실제 RDS postgres16의 slot/sender 최소 허용값5를 조회해 trial slot 한도를5로 반영했다. 실제 시험 slot은1개다.
- `local-smoke/check.py --compact --s3`: snapshot/insert/update/delete·1000행 burst·중단 후 전달·broker 재생성/offset 보존·mTLS/ACL/JMX 통과. 최종 JSON1007개/1007건과 Connect 중단 중 추가한 행의 S3 저장을 확인했다. OOM/재시작 없음. 파일 읽기 병렬화 후 동일1006개 초기 파일을 읽는 개별 probe도 통과했다.
- Helm/CRD/Connector 예시 검사 및 잘못된 입력28개 거부 통과. Terraform mock48개 통과, rds/network/ecr/workload-access validate 통과, Python compile/diff whitespace 검사 통과.
- 실제 AWS read-only plan: RDS 생성2/변경1, network 변경1, ECR 생성1. 삭제/교체 없음. workload-access plan은 live network state에 필요한 AbortMultipartUpload가 없어 사전조건으로 거부됐고, network 적용 뒤 재plan이 필요하다. 이를 mock 통과나 실제 IAM 검증으로 표시하지 않았다.
- 위 read-only plan은 준비 단계 기록이다. 이후 사용자 승인으로 RDS parameter group/접속 규칙, network endpoint action, ECR Connect 저장소, 실행별 prefix 전용 Pod Identity 역할을 실제 적용했다. 기존 리소스 교체 없이 ECR push/digest 고정과 RDS 재부팅을 수행했다.
- 재부팅 전 실제 DB verify-full TLS 및 다른 접속을 확인했다. DBeaver idle 세션3개에 열린 트랜잭션·실행 중 작업이 없음을 확인하고 사용자에게 접속 해제를 알린 뒤 재부팅했다. 시험 대상 clothes DB의 업무 테이블 수는 전후 모두0이다. 다른 DB에 DDL/DML을 수행하지 않았다.
- RDS 실제 논리 복제 on/wal_level logical/slot 한도5/WAL256MB를 SQL로 확인했다. 파라미터 API의 sender 요청값은10이고 실제 SQL 유효값은20(pending_restart=false)이었다. 차이 원인은 미확정으로 기록하며 정확히10 적용됐다고 주장하지 않는다. 시험에는 slot/CDC 연결 각1개만 사용했다.
- 실제 AWS `RDS → Debezium → mTLS Kafka → S3 Sink → S3`에서 초기 snapshot·추가·수정·삭제 및 CDC stopped/running 전환 중 추가된 데이터의 이어받기가 통과했다. allowlist 밖 테이블은 publication에서 제외되며 이후 허용 테이블의 추가 이벤트도 도착했다. 최종 JSON6개/6건이다.
- 실제 Connect Pod Identity로 허용 prefix 읽기/쓰기 성공, 소유자가 만든 **존재하는** 다른 prefix canary 읽기/쓰기403을 확인했다. ground_truth/incident_log의 GetObject/PutObject는 IAM simulation에서 거부됐다. 조사 에이전트용 역할 배포를 뜻하지 않는다.
- 실행 전 비어 있음을 확인한 `infra-smoke/<실행ID>/`, `infra-smoke-denied/<실행ID>/`만 사용했다. 종료 후 S3 데이터6개와 권한 canary2개에 해당하는 **모든 버전8개**를 삭제하고 현재 객체·이전 버전·삭제 표시·미완료 업로드0을 확인했다.
- Source 정지/slot inactive 확인 후 Connector2개·Connect Pod·KafkaUser/TLS Secret·시험 토픽/내부 토픽을 제거하고 기존 Helm manifest를 복원했다. DB schema/table/role/publication/slot, 임시 Pod/Secret, 시험 IAM role/policy/association을 제거했다. 추가 DB 접속 규칙과 endpoint action도 복원했다. 기존 Kafka PVC UID는 유지됐다.
- 시험 전/중/후 t3a.large 노드는 모두1대다. 종료 후 Kafka 관련 Pod4개 Ready. 전송 중 단일 표본은 노드0.265vCPU/3185.5MiB, Connect0.044vCPU/734.1MiB working set이며 피크/전체 플랫폼 용량 검증은 아니다.
- 배포한 동일 이미지 Trivy 스캔은 Critical0/High42/Medium251/Low138, 억제0이다. 잔여 취약점 검토를 완료한 운영 이미지로 표시하지 않는다. AWS 자격증명은 이미지에 넣지 않았고 임시 ECR 로그인 토큰을 삭제했다.
- 남긴 기반은 RDS 논리 복제 설정과 데이터 없는 Connect ECR 이미지다. 시험 런타임·계정·slot·더미 데이터는 남기지 않는다. 실배포용 비공개 tfvars를 갱신했고 기본 Connect는 계속 비활성이다. PR 승인/머지는 팀원에게 남긴다.
- 정리 후 실제 rds/network/ecr/workload-access plan 모두 변경 없음. 최종 EKS ACTIVE·Kafka4 Pod Ready/재시작0, 암호화 gp3 20GiB Bound/in-use/Retain, 임시 infra-probe Pod/Secret0, JMX HTTP/지표65개를 확인했다.
- 다음: 팀의 업무 테이블·토픽·S3 형식/경로·계정·WAL 예산 확정 후 실제 업무용 연결. Fargate·Airflow·Athena 및 에이전트 권한 분리는 별도다.
