# 인프라 남은 작업과 미정 사항

기준: 2026-10-23, origin/main b0185ff. Git·PR·ECR·실행 상태를 읽기 확인한 결과다. 조사 중 배포·삭제·DAG 실행은 하지 않았다. 적용 완료, 업무 실행 성공, main 반영은 각각 구분한다.

## 이미 완료한 기반

| 구간 | 확인한 상태 | 아직 증명하지 않은 것 |
|---|---|---|
| RDS → Kafka → Bronze | CDC source·기존 S3 Sink·Bronze v2 Sink의 connector/task RUNNING | RUNNING만으로 모든 이벤트의 S3 도착·정합성을 보장하지 않음 |
| Kafka 보관 | 7일 설정 적용·복구 검증, PR #86 main 머지 | 20GiB 디스크로 모든 유입량의 7일 보관을 보장하지 않음 |
| 모니터링 | Prometheus 수집·Grafana 플러그인 복구·인프라 이메일 알림 적용 | 전체 서비스 장애 시나리오 및 업무 성공 탐지는 별도 |
| Spark 기반 | Spark 4.2.0 / Python 3.10.12 기본 이미지 발행, pipelines SA/RBAC·Driver/Executor S3/Pod Identity 적용 | 실제 업무 분산 실행·S3 출력·동시 작업 메모리 검증은 남음 |
| 판정·조사 | 두 이미지 digest 연결·GitDagBundle 등록·import 오류 없음, 두 DAG paused | 판정/조사 이미지 실제 실행·모델 호출·5분 주기 실측은 남음 |
| 카탈로그 | #53 표 4개·뷰 생성, 실제 판정 ServiceAccount INSERT/조회 및 시험 데이터 정리 성공 | 전체 원장/R6 입력과 업무 결과 검증은 별도 |
| Bedrock | JP Haiku 4.5 프로필 및 두 목적지 모델로 조사 역할 권한 제한 | 실제 조사 Pod의 Converse 호출·응답은 아직 시험하지 않음 |
| 승인 API 기반 | dashboard/airflow-api-client Secret 존재, username/password 키 확인 | 대시보드 최신 이미지·환경변수 반영 및 승인→재처리 전체 검증은 남음 |

현재 agent/pipelines에는 실행 Pod가 없고 Spark NodePool도 없다. 판정·조사 DAG는 paused이며 실행 이력 0개를 확인했다. 노드 증설·정기 업무 실행을 시작한 상태가 아니다.

## 지금 남은 작업과 담당

| 우선 | 작업 | 인프라 담당이 할 일 | 팀원에게 확인할 것 |
|---|---|---|---|
| 1 | 실환경과 Git 맞추기 | 적용된 인프라 코드·공통 설정을 검토 가능한 PR로 공유 | #89의 이미 적용된 Bronze v2 변경 검토·머지 |
| 2 | Silver·Gold A 첫 실행 | 최종 이미지 설정 연결 후 노드 1대분을 잠깐 활성화하고 수동 시험·정리 | #87 자원 정렬 리뷰, 사용할 최종 업무 이미지 digest와 고정 입력/기대 결과 |
| 3 | Gold B 실행 연결 | 확정된 계정별 Kafka/S3 권한·배포·자원·체크포인트 경로 연결 | 상시 ingest 진입점·이미지·검사기·Kafka 사용자·토픽/출력/체크포인트 명세, collector 이미지/주기 |
| 4 | 판정·조사 실제 검증 | 수동 1회 실행, 권한/시간/자원/모델 접속 확인 후 주기 활성화 판단 | 업무 입력 준비 및 판정·조사 결과 확인 |
| 5 | 승인·재처리 연결 | 승인 Pod 역할·Secret/env 및 재처리 실행 권한 대조, 연결 시험 | 대시보드 이미지 반영, 최종 재처리 DAG ID·입력·완료 조건 |
| 6 | Silver·Gold A Athena 공개/R6 | 확정된 DDL·경로에 맞춰 카탈로그와 읽기 권한 연결 | #87 공개 명세 합의, 완료 목록/completed_at·R6 소비 구현 |

Silver·Gold A 업무 ECR에는 b0185ff 커밋 태그 이미지가 이미 존재한다. 따라서 단순히 “이미지 push를 기다림”으로 두지 않는다. #87은 아직 열려 있고 자원 정렬이 포함돼 있으므로 담당자가 그 이미지를 최종으로 쓸지, 머지 후 새 커밋으로 발행할지 확인해야 한다. 고정 거래 입력과 7,900원 기대값은 이미 전달된 기록이 있으며 실행 직전 객체/ETag와 맞춘다.

main에는 Gold B collector·재처리·compact 코드가 있다. 상시 적재 streaming_ingest 진입점은 현재 main에서 확인하지 못했다. “Gold B 전체를 아직 안 만들었다”거나 “코드가 있으니 이미 실행 가능하다”고 단정하지 않는다.

## 아직 정하지 않은 것

| 항목 | 현재 기준 | 남은 결정 |
|---|---|---|
| Spark 자원 배치 | t3a.large 최대 한 대분 준비, 현재 노드풀 미기동 | Gold B 상시 몫과 Gold A 배치의 동시 실행/대기, 작업별 Executor/메모리 한도 |
| 한 대에 들어가는지 | Gold B 메모리/실행 코드 실측 없음 | 먼저 작은 설정으로 측정. 부족하다고 확정하거나 추가 노드부터 만들지 않음 |
| Spark/Python 호환 | 인프라는 4.2.0 / 3.10.12 유지 | Gold B 코드가 여기에 맞는지 검증, 필요할 때 업무 컨테이너 분리. 보류한 4.1.3/3.11 후보를 자동 적용하지 않음 |
| Bronze v2 전환 | 기존 Sink와 v2가 모두 RUNNING, PR #89 열림 | 재처리·Silver가 읽을 경로, 기존 Sink 병행/종료 시점은 데이터 담당과 확정 |
| Gold A 공개 계약 | #87에 검토안이 있음 | channel/run_id 고정 조회·완료 공개·R6 목록/완료 시각 구현 합의. current.json만으로 Athena가 자동 변경되는 구조로 보지 않음 |
| Gold B 재시작·상시 운영 | Kafka/Spark checkpoint 계약이 필요 | 코드/경로/오프셋·인증·자원 확정 후 재시작 검증 |

## 검토 중 PR

- [#87](https://github.com/josiah113366-sketch/clothes-query/pull/87): Silver·Gold A 자원을 기존 인프라 프로필에 맞춤. Glue 공개 명세는 검토안이며 완료 목록·completed_at·카탈로그는 미구현이라고 본문에 명시돼 있다.
- [#89](https://github.com/josiah113366-sketch/clothes-query/pull/89): Bronze v2 Sink/ACL/S3 권한. 본문은 실환경 적용 완료를 명시하고 실제 connector도 RUNNING이다. main과의 차이를 우선 정리할 대상이다.
- [#90](https://github.com/josiah113366-sketch/clothes-query/pull/90): 승인 코드/대시보드의 Kafka 보관 기본값을 7일로 맞춤. 브로커 변경과 별개이며 판정·조사 이미지에 영향 없다고 명시돼 있다.
- [#73](https://github.com/josiah113366-sketch/clothes-query/pull/73), [#74](https://github.com/josiah113366-sketch/clothes-query/pull/74): 기존 통합 공유 PR. 이후 로컬 적용한 변경이 모두 원격에 있다고 가정하지 말고 내용을 갱신한 뒤 검토한다.

위 PR 목록 확인은 코드 리뷰/승인 완료를 뜻하지 않는다. 자동 머지는 하지 않는다.

## 보류 및 미게시 작업

자동 CD의 앱별 규칙·Argo CD Application 연결, 비용/고가용성 보강·Kafka 복제/복구 설계는 보류 상태다. 인프라 장애 이메일 알림은 이미 연결했으며 과거 Budget 후보와 구분한다.

중요한 실환경 적용 후속이 아직 로컬 브랜치에 있다.

- infra/silver-gold-a-connections: ECR·Spark 이미지·endpoint·SA/RBAC/IAM/Pod Identity 적용 기록.
- infra/agent-bedrock-catalog: Bedrock·#53 카탈로그·시험·판정/조사 ConfigMap/Git bundle 연결 기록.
- infra/grafana-plugin-recovery 및 부모 운영 브랜치: Grafana 복구·인프라 알림 후속. Kafka만 분리한 #86은 이미 머지됐으므로 다시 중복 반영하지 않는다.
- 루트 infra/gold-b-spark-image에는 중지한 실험 이미지 변경이 미커밋 상태로 남아 있다. 현재 실행 기반으로 적용된 것으로 취급하거나 정리 중 지우지 않는다.

## 다음 작업 순서

1. 완료된 테스트의 작은 결과 기록을 남기고 대형 임시 검사 캐시를 정리한다. 실제 작업 폴더는 보존한다.
2. #89 및 미게시 인프라 변경을 정리해 실환경을 오래된 코드로 되돌릴 가능성을 줄인다.
3. #87·최종 업무 이미지 확인과 Gold B 실행 명세를 받는다.
4. 라지 한 대 기준의 작은 Spark 자원안으로 첫 실행을 검증한다. 추가 노드/고가용성은 측정 후 결정한다.

현재 조사 과정에서는 캐시·Docker·브랜치·AWS 자원을 삭제하지 않았다.
