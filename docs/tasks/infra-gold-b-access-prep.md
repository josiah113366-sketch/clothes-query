# 작업 지시서: infra/gold-b-access-prep

상태: 현황 확인 완료·실행 위치 선택 대기 / AWS 변경 없음

## 목표와 승인된 범위

2026-10-21 팀원에게 받은 Gold B 접근 요청을 사용자가 하나씩 지정하며 준비하도록 요청했다. 조사 에이전트·판정 업무 코드는 팀원 담당이다. 인프라는 읽기/쓰기 역할 분리, Athena workgroup, 정답표 차단, Airflow 실행 환경 연결을 담당한다. 실제 계정/ARN은 공개 Git에 넣지 않는다. 보류한 CI/CD와 비용 알림은 이번 작업에 포함하지 않는다.

## 받은 결정

| 항목 | 내용 |
|---|---|
| 조사 데이터 | Glue DB gold_b, 지정 데이터 버킷의 gold_b/ |
| 조사 역할 | 읽기 전용, ground_truth/ 전체 접근 차단 |
| 판정 역할 | 필요한 데이터 읽기, 이상 이력·순찰 기록·재처리 기록 쓰기 |
| Athena | 에이전트 전용 workgroup, 조회 결과는 gold_b/ 밖, 스캔량 제한 희망 |
| 개발자 | 제공 IAM 사용자 존재 확인. 실제 ARN은 비공개 기록에만 보관 |
| Airflow | 팀원은 3.3 계열을 추천. 최신 안정판 여부와 Helm 호환성을 공식 배포 정보로 검증한 뒤 정확한 버전 확정 |

## 현황 확인과 주의할 차이

- 도쿄 AWS에서 gold_b Glue DB는 아직 없다. Athena workgroup은 primary만 있고 프로젝트의 에이전트/판정/Airflow 이름 역할은 아직 없다.
- 개발자는 직접 연결 정책이나 permissions boundary가 없지만 공통 그룹 정책에서 s3:*, athena:*, glue:*, iam:*, sts:*를 Resource *로 허용받는다. 별도 Allow 추가는 이 권한을 제한하지 않는다. 공통 그룹 정책은 변경하지 않는다. 운영 제한 역할로 검증하더라도 원래 개발자 사용자 자체가 정답표를 못 읽는다고 보장할 수 없다. 실제 상위 정책·리소스 정책에 따른 최종 권한은 별도 검증 대상이다.
- origin/pipelines/gold-b의 DDL에는 원장 4개와 reprocess_events가 있다. 설계에는 payment_attempts/payment_conflicts/malformed_messages의 뷰 3개가 있어 팀원 문자 “뷰 2개”와 다르다. anomaly/detection_runs DDL·최종 물리 위치와 쓰기 API는 추가 확인한다. 원장 전체를 임의로 쓰기 허용하지 않는다.
- 기존 infra/athena-query-base 브랜치에는 판정용 workgroup 후보 clothes-query-dev-detection, 쿼리당 1GiB, Athena 관리형 임시 결과 저장 코드/plan이 있다. 아직 미적용이며 이번 브랜치에 병합하거나 배포하지 않았다. 관리형 결과는 일반 S3 결과 경로 지정과 다른 방식이므로 선택 전에 팀원 소비 코드와 맞춘다. 스캔량 상한은 월 예산이나 SELECT-only 보장을 의미하지 않는다.
- 기존 workload-access 모듈은 EKS Pod Identity용 S3 prefix Allow만 구현한다. 이번 요구에는 Athena/Glue, 명시적 금지 경로, 실행 역할별 결과 분리가 추가로 필요하다. 기존 Bronze Sink 역할은 변경하지 않는다.

## 순서와 남은 선택

1. **실행 위치 선택:** 판정 잡·조사 에이전트의 EKS 별도 Pod 실행 또는 외부 서비스 여부를 사용자에게 질문했다. 답변 전 EKS namespace/ServiceAccount 또는 다른 서비스 trust를 확정하지 않는다.
2. **역할·workgroup 이름:** 실행 위치 답변 후 조사·판정 역할과 workgroup을 구분해 명세화한다. 개발자는 필요시 개발용 제한 역할 세션을 사용하되 원래 사용자 권한과 혼동하지 않는다.
3. **물리 경로와 결과 저장:** 최종 테이블/뷰 목록, 이상/순찰/재처리 쓰기 prefix·방식, Athena 관리형 결과 또는 별도 S3 결과 prefix 선택. 같은 결과 저장소 공유로 역할 분리가 깨지지 않게 한다.
4. **코드·검증:** 기존 역할/리소스와 중복 없는 Terraform 코드, mock·정적 검증, 실제 plan을 만든다. 승인된 범위에서만 실제 적용/접근 테스트를 진행한다.
5. **Airflow:** 실제 Helm chart/버전/Auth Manager/메타데이터 DB/로그 공급·자원 여유를 확인한다. 같은 LocalExecutor 자격 증명을 공유하는 DAG를 역할 분리로 간주하지 않는다. 승인 화면 API와 업무 DAG는 담당자 계약으로 연결한다.

## 작업 결과

- 기존 infra 규칙·workload-access·보류 중 Athena 코드·Airflow 문서·최신 Gold B 브랜치를 대조했다.
- 개발자 IAM 정책, 도쿄 Glue DB·Athena workgroup·역할 목록을 읽기 전용 조회했다. 실제 값은 Git 제외 경로에 저장했다.
- AWS 리소스/권한/데이터는 생성·수정하지 않았다. 실행 위치 선택과 테이블 계약 확인 후 다음 단계로 진행한다.
