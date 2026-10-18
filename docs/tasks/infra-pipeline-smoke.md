# 시험 데이터 경로 연결

상태: 로컬 검증·AWS 적용 준비 완료 / AWS 적용 대기 · 2026-10-18

## 요청과 범위

업무 테이블·제네레이터·Airflow가 미정이어도 숫자 시험 데이터를 RDS/PostgreSQL → Debezium → Kafka → S3로 전달하는 연결을 먼저 준비한다. 실제 AWS 적용과 로컬 S3 호환 API 검증을 구분한다. PR 승인·머지는 팀원이 한다.

## 작업 계획

1. 기존 local CDC/mTLS/재시작 검사를 재사용해 선택적 S3 Sink 검사를 추가.
2. Kafka Connect에 Sink용 명시적 topic/group 읽기 ACL을 선택적으로 지원.
3. 기존 Kafka/PVC·업무 데이터와 분리한 AWS 시험 설정·SQL·적용/종료 절차 준비.
4. 로컬 실제 송수신·저장, Helm/CRD, AWS read-only plan 확인. apply/reboot는 검토 후 담당자 실행.

## 완료 확인

- `python -X utf8 infra/platform/kafka/local-smoke/check.py --compact --s3`
- `python infra/platform/kafka/verify/check.py --helm .cache/helm/windows-amd64/helm.exe` (검증 venv 사용)
- 시험 overlay의 Helm 렌더 및 Connector 공식 CRD 검사.
- AWS plan 변경/삭제/교체 여부 확인. 실제 적용 미수행 사실 기록.

## 작업 결과

- 기존 CDC 검사를 선택적으로 확장해 S3 Sink 12.1.13과 Moto S3 fixture를 추가했다. 운영용 DB·업무 토픽·S3 경로 없이 숫자 데이터로 연결을 확인한다. 기본 실행은 기존 CDC-only 동작을 유지한다.
- Connect에 선택적 literal consumeTopics/consumerGroups ACL을 추가했다. 기본은 빈 배열이며 source-only 권한을 넓히지 않는다. undefined topic·group 누락·wildcard 입력을 거부한다.
- AWS용 시험 schema/전용 DB 역할/토픽·72시간/Connect·S3 prefix와 비활성 overlay, Connector CR, 초기화 SQL, 최소 S3 역할 및 적용/종료 절차를 준비했다. 실제 RDS postgres16의 slot/sender 최소 허용값5를 조회해 trial slot 한도를5로 반영했다. 실제 시험 slot은1개다.
- `local-smoke/check.py --compact --s3`: snapshot/insert/update/delete·1000행 burst·중단 후 전달·broker 재생성/offset 보존·mTLS/ACL/JMX 통과. 최종 JSON1007개/1007건과 Connect 중단 중 추가한 행의 S3 저장을 확인했다. OOM/재시작 없음. 파일 읽기 병렬화 후 동일1006개 초기 파일을 읽는 개별 probe도 통과했다.
- Helm/CRD/Connector 예시 검사 및 잘못된 입력28개 거부 통과. Terraform mock48개 통과, rds/network/ecr/workload-access validate 통과, Python compile/diff whitespace 검사 통과.
- 실제 AWS read-only plan: RDS 생성2/변경1, network 변경1, ECR 생성1. 삭제/교체 없음. workload-access plan은 live network state에 필요한 AbortMultipartUpload가 없어 사전조건으로 거부됐고, network 적용 뒤 재plan이 필요하다. 이를 mock 통과나 실제 IAM 검증으로 표시하지 않았다.
- AWS 리소스 변경·DB 재부팅·ECR push·실제 DB SQL 실행 없음. PR 승인/머지는 팀원에게 남긴다.
- 다음: 검토된 설정으로 담당자 AWS 적용, network 반영 후 역할 재plan, 이미지 스캔/push·시험 Secret/DB 초기화·Connect 활성화, 실제 RDS → S3 및 다른 prefix 접근 거부·자원/비용 확인.
