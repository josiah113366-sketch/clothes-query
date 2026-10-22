# 작업 지시서: infra/gold-b-access-prep

상태: 조회용 자원·EKS 실행 신원 연결 및 합성 실측 완료·검토 대기 / 판정 기록 쓰기·Airflow·업무 실행 후속

2026-10-21 Terraform 12 roots/58 mock plan 통과 후 [PR #40](https://github.com/josiah113366-sketch/clothes-query/pull/40)을 생성했다. Airflow PR #41의 선행 기반이며 실제 업무 쓰기 권한은 여전히 미설정이다. 이번 Git 정리에서 AWS 재적용·PR 승인·머지는 하지 않았다. 아래 미푸시 표현은 과거 작업 시점 기록이다.

PR 정리: 최신 main을 반영했다. 이 브랜치는 Gold B 권한과 agent namespace/ServiceAccount만 포함하며 Airflow 설치는 `infra/airflow-runtime`에서 이 브랜치를 기반으로 별도 검토한다. CI/CD·비용 알림·과거 단일 Athena 후보는 포함하지 않는다. README의 과거 namespace 미연결 표현도 실제 검증 상태로 갱신했다.

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
| 운영 실행 위치 | 사용자가 두 작업 모두 기존 EKS의 별도 Pod로 실행하도록 선택. 작업별 ServiceAccount/IAM 역할 분리 |
| 조회 결과 저장 | 사용자가 기존 버킷의 athena-results/investigation/ 및 athena-results/detection/ 분리 저장을 승인. 나중에 변수로 변경 가능 |
| Airflow | 팀원은 3.3 계열을 추천. 최신 안정판 여부와 Helm 호환성을 공식 배포 정보로 검증한 뒤 정확한 버전 확정 |

## 현황 확인과 주의할 차이

- 도쿄 AWS에서 gold_b Glue DB는 아직 없다. Athena workgroup은 primary만 있고 프로젝트의 에이전트/판정/Airflow 이름 역할은 아직 없다.
- 개발자는 직접 연결 정책이나 permissions boundary가 없지만 공통 그룹 정책에서 s3:*, athena:*, glue:*, iam:*, sts:*를 Resource *로 허용받는다. 별도 Allow 추가는 이 권한을 제한하지 않는다. 공통 그룹 정책은 변경하지 않는다. 운영 제한 역할로 검증하더라도 원래 개발자 사용자 자체가 정답표를 못 읽는다고 보장할 수 없다. 실제 상위 정책·리소스 정책에 따른 최종 권한은 별도 검증 대상이다.
- origin/pipelines/gold-b의 DDL에는 원장 4개와 reprocess_events가 있다. 설계에는 payment_attempts/payment_conflicts/malformed_messages의 뷰 3개가 있어 팀원 문자 “뷰 2개”와 다르다. anomaly/detection_runs DDL·최종 물리 위치와 쓰기 API는 추가 확인한다. 원장 전체를 임의로 쓰기 허용하지 않는다.
- 기존 infra/athena-query-base 브랜치에는 판정용 workgroup 후보 clothes-query-dev-detection, 쿼리당 1GiB, Athena 관리형 임시 결과 저장 코드/plan이 있다. 아직 미적용이며 이번 브랜치에 병합하거나 배포하지 않았다. 관리형 결과는 일반 S3 결과 경로 지정과 다른 방식이므로 선택 전에 팀원 소비 코드와 맞춘다. 스캔량 상한은 월 예산이나 SELECT-only 보장을 의미하지 않는다.
- 기존 workload-access 모듈은 EKS Pod Identity용 S3 prefix Allow만 구현한다. 이번 요구에는 Athena/Glue, 명시적 금지 경로, 실행 역할별 결과 분리가 추가로 필요하다. 기존 Bronze Sink 역할은 변경하지 않는다.

## 순서와 남은 선택

1. **실행 위치 결정:** 사용자가 두 작업 모두 기존 EKS 별도 Pod로 선택했다. Pod Identity를 사용하고 업무별 ServiceAccount를 분리한다. Airflow scheduler 자체 역할과 판정/조사 업무 실행 역할은 구분한다. 실제 Pod 배포는 담당자 코드/이미지 및 자원 설정 후 진행한다.
2. **역할·workgroup 이름:** 아래 명세로 준비한다. 개발자는 필요시 개발용 제한 역할 세션을 사용하되 원래 사용자 권한과 혼동하지 않는다.
3. **물리 경로와 결과 저장:** 최종 테이블/뷰 목록, 이상/순찰/재처리 쓰기 prefix·방식, Athena 관리형 결과 또는 별도 S3 결과 prefix 선택. 같은 결과 저장소 공유로 역할 분리가 깨지지 않게 한다.
4. **코드·검증:** 기존 역할/리소스와 중복 없는 Terraform 코드, mock·정적 검증, 실제 plan을 만든다. 승인된 범위에서만 실제 적용/접근 테스트를 진행한다.
5. **Airflow:** 실제 Helm chart/버전/Auth Manager/메타데이터 DB/로그 공급·자원 여유를 확인한다. 같은 LocalExecutor 자격 증명을 공유하는 DAG를 역할 분리로 간주하지 않는다. 승인 화면 API와 업무 DAG는 담당자 계약으로 연결한다.

## 운영 자원 이름과 연결 명세

프로젝트 이름 규칙에 따른 준비용 이름이다. 실제 자원 생성이나 Pod 배포를 의미하지 않는다. 업무 Pod용 namespace는 agent로 정하고, Airflow 본체의 airflow namespace와 분리한다. 생성 전 기존 namespace/ServiceAccount/Pod Identity association 중복을 확인한다.

| 용도 | namespace / ServiceAccount | IAM 역할 이름 | Athena workgroup |
|---|---|---|---|
| 판정 잡 | agent / detection-job | clothes-query-dev-detection-job | clothes-query-dev-detection |
| 조사 에이전트 | agent / investigation-agent | clothes-query-dev-investigation-agent | clothes-query-dev-investigation |

운영 역할의 trust는 지정 namespace/ServiceAccount의 EKS Pod Identity용이다. 개발자 개인 ARN을 운영 역할 trust에 자동 추가하지 않는다. Airflow가 업무 Pod를 생성하는 RBAC는 별도 연결하며 업무 역할 자체에는 Pod 생성 권한을 주지 않는다. 스캔량 상한은 우선 쿼리당 1GiB 후보로 준비하되 비용 예산과 구분한다.

사용자가 S3 결과 경로를 승인해 gold_b/ 밖의 athena-results/detection/ 및 athena-results/investigation/로 구분한다. 원장 읽기 전용 에이전트도 자기 쿼리 결과 경로의 제한된 쓰기는 필요하다. 팀원이 읽는 이상/순찰/재처리 업무 기록과 쿼리 임시 결과는 다르다. 모듈 입력 results_prefixes로 변경 가능하며 과거 결과는 자동 이동/삭제하지 않는다. 결과 저장 파일 생성은 실제 Athena 쿼리 실행 시 발생한다.

## 구현 범위

후속 사용자 결정: “응 이것도 일단 하고 나중에 수정할수있게 변수로 빼자” 요청에 따라 workgroup 이름도 독립 map 입력으로 노출하고, 이미 변수화된 결과 경로·스캔 상한과 함께 현재 확정한 조회용 자원을 실제 적용한다. 이 요청을 이번 신규8개 적용의 승인으로 처리한다. 기존 사용자/공통 그룹이나 미확정 업무 기록 쓰기는 변경하지 않는다.

- 새 gold-b-access 모듈/스택에서 workgroup 2개, IAM 역할 2개, inline policy 2개, Pod Identity association 2개를 준비했다. 기존 workgroup/역할/동일 SA association이 없음을 사전 조회한다.
- Glue DB gold_b 메타데이터와 S3 gold_b/ 읽기, 자기 결과 prefix 읽기·쓰기만 허용하며 ground_truth/ 객체와 해당 prefix 목록을 명시 Deny한다. trust는 클러스터/namespace/SA에 바인딩하고 개발자 신원을 포함하지 않는다.
- 조회 결과 경로·SSE-S3·bucket owner·쿼리당 1GiB를 workgroup에서 강제한다. 추가 CloudWatch 지표 게시를 끈다. SQL 자체의 SELECT-only 기능이나 월 비용 상한이라고 주장하지 않는다.
- 판정 이력 쓰기 prefix는 미확정이라 빈 목록이다. mock의 예제 쓰기 경로는 테스트용일 뿐 실제 배포 입력이 아니다. 실제 Glue DB/table·Kubernetes namespace/SA·업무 Pod·DAG·실제 개발자 제한은 이번 코드에서 생성/수정하지 않는다.
- 기존 infra/athena-query-base는 아직 미적용이며 동일 판정 workgroup을 중복 소유하면 안 된다. 이번 두 workgroup 스택으로 대체하는 방향으로 정리하고 예전 스택을 함께 배포하지 않는다.

## 작업 결과

- 기존 infra 규칙·workload-access·보류 중 Athena 코드·Airflow 문서·최신 Gold B 브랜치를 대조했다.
- 개발자 IAM 정책, 도쿄 Glue DB·Athena workgroup·역할 목록을 읽기 전용 조회했다. 실제 값은 Git 제외 경로에 저장했다.
- 사용자가 EKS 별도 Pod 실행과 분리된 S3 결과 경로를 확정해 모듈/스택·테스트·안내를 준비했다. 실제 apply·업무 SQL·데이터 쓰기는 수행하지 않았다.
- 모듈/스택 fmt·스택 validate·기존 고정 AWS provider 6.68.0으로 mock 7개 통과. 두 역할/결과/workgroup 분리·신뢰 바인딩·정답표 Deny·기록 쓰기 opt-in, 중첩 결과 경로·금지 결과 경로·전체 gold_b 쓰기·너무 작은 스캔 상한·부족한 endpoint 권한 거부를 확인했다. 초기 PowerShell 직접 호출은 테스트 0개로 종료돼 검증으로 인정하지 않고 Python argv 호출로 실제 test summary 7 passed를 확인했다.
- 실제 도쿄 plan은 신규8·수정0·삭제0이다. 기존 버킷·네트워크·EKS·Bronze Sink·개발자 그룹에는 변경이 없다. 판정 이력 쓰기 목록은 비어 있다. 실제 이름이 같은 역할/workgroup/association도 사전 조회에서 없었다.
- 생성 예정 inline policy를 AWS IAM SimulateCustomPolicy에 전달해 S3 객체 읽기/버전 읽기/쓰기/삭제 40개, 자기·상대·primary workgroup 조회 시작 6개, S3 일반/버전 목록과 root/상대/정답표 prefix 20개, 총 66개 허용·거부 조합을 통과했다. CLI의 policy list 전달과 여러 resource의 결과 집계 구조를 수정해 검증을 완료했으며 정책 자체를 넓히지 않았다. 이는 실제 Pod 세션·버킷/Lake Formation/상위 정책·Athena 업무 조회 검증을 대신하지 않는다.
- Git 제외 private input/backend/plan/시뮬레이션 요청에만 실제 계정/버킷/ARN을 저장한다. 초기 코드 검증 단계에서는 실제 역할이 없었으며 아래 후속 적용으로 생성했다.
- 다음 입력은 판정이 쓰는 anomaly/detection_runs/reprocess_events의 최종 S3 prefix와 S3 직접 Parquet append 또는 Athena INSERT 등 저장 방식이다. 이후 namespace/ServiceAccount·Airflow·업무 이미지 배포와 실제 경로 허용/금지 검증을 연결한다.

## 후속: 변수 노출과 실제 적용

사용자의 후속 진행 요청으로 workgroup_names를 모듈과 스택에 노출했다. results_prefixes와 bytes_scanned_cutoff_per_query도 공용 tfvars에서 편집한다. 변수로 바꾼 이름·경로·한도가 IAM과 함께 갱신되는 검사, 같은 workgroup 이름/primary 거부를 추가해 mock 10개를 통과했다. 이름 변경은 리소스 교체일 수 있고 과거 결과는 자동 이관되지 않으므로 변경 때마다 plan과 실행 코드 설정을 대조한다.

최신 origin/main 반영 확인 후 새 plan(생성8·수정0·삭제0), S3/Workgroup 시뮬레이션 46개 재검증을 거쳐 적용했다. 실제 두 workgroup의 ENABLED·쿼리당 1GiB·각각의 결과 경로 강제·SSE-S3·추가 CloudWatch 지표 비활성을 확인했다. IAM inline policy가 검토한 문서와 일치하고 각 역할 trust/Pod Identity association이 지정 namespace/ServiceAccount에 연결됨을 확인했다. 사후 plan 변경 없음이다.

실제 Glue DB/table·namespace/ServiceAccount/Pod를 만들거나 업무 쿼리를 실행하지 않았다. 실제 Pod에서 Athena 조회/정답표 차단 성공까지 검증된 상태는 아니다. 판정 이력 쓰기는 빈 목록 그대로다. 개발자 개인/그룹 정책도 바꾸지 않았다. push·PR·승인·머지는 수행하지 않았다.

## 후속: EKS 실행 신원 연결과 실제 접근 검사

사용자가 API/ALB 현황 확인 후 “하던거나 마저 하자”라고 요청해 기존 접근 준비를 이어갔다. agent namespace가 없음을 확인하고 별도 manifest로 namespace와 detection-job/investigation-agent ServiceAccount를 생성했다. 기본 Kubernetes API 토큰 자동 마운트는 비활성화하고 기존 Pod Identity association을 사용했다. AWS 키·Secret을 만들거나 주입하지 않았다. 운영 업무 Pod는 아직 배포하지 않았다.

현재 실제 노드는 Kafka용 t3a.large 한 대와 API용 t3a.medium 한 대다. API용 namespace는 api이며 내부 ALB 연결과 헬스체크 정상을 읽기 전용 확인했다. 이번 검사는 기존 Kafka compute 노드에 소형 임시 Pod를 고정해 추가 노드 생성을 피했다. boto3가 포함된 기존 사설 리뷰 이미지의 digest를 사용하되 앱 기본 명령·리뷰/Bedrock 프로그램은 실행하지 않았다.

각 역할 12개, 총 24개 실제 접근 검사를 통과했다. 올바른 Pod Identity 역할, 합성 gold_b 객체 읽기·prefix 목록, 자기 결과 쓰기/읽기·Athena SELECT 1 및 결과 조회는 성공했다. 정답표 객체·이전 버전·prefix 목록, 상대 결과, 버킷 root 목록, 업무 데이터 쓰기, 상대 workgroup 사용은 거부됐다. 실제 정답표/업무 파일 내용은 읽지 않았다. 합성 객체는 실제 원장/정답표 처리 위치가 아닌 각 상위 prefix의 고유 _infra-checks/ 아래에 만들었다.

정리: 임시 Pod 2개 삭제, 합성 source/truth/result 객체와 SELECT 1 결과/metadata의 총 10개 버전 삭제, 각 고유 key/query ID prefix의 남은 version/delete marker 0개를 확인했다. agent namespace Pod 0개, 노드 수 2개 유지다. namespace/SA·운영 역할·workgroup은 의도된 기반으로 남긴다. 캐시의 실행 기록/ID는 Git 제외이며 업무 SQL·스캔 상한 초과·부하 테스트를 수행한 것은 아니다. probe.py 문법·manifest 구조·Ruff 검사 및 diff check도 확인했다.

다음은 판정 이력 쓰기 저장 계약과 Airflow 설치 설정을 맞추는 일이다. 실제 업무 코드/이미지·DAG·scheduler의 업무 Pod 생성 RBAC·카탈로그/뷰 연결은 미완료다. 과거 문단의 미생성/미검증 상태는 해당 시점 기록이며 현재 상태는 이 절을 따른다.
