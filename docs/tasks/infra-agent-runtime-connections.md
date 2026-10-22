# 판정·조사 실행 연결 기반

상태: 인프라 연결 적용·검증 완료, 자격증명 복제 승인 및 담당자 입력 대기

## 사용자 범위

2026-10-22 사용자 요청으로 저장·배포 경로, 실행 권한, 자원과 연결 검증만 진행한다. DAG·업무 SQL·판정/조사/승인 로직·모델 선택은 담당자 소유다. Argo CD와 일반 CI/CD는 보류하며 자동 머지·자체 승인 리뷰는 하지 않는다.

## 작업

- 현재 Airflow 3.3.2와 Helm 1.22.0에서 Git DAG 공급을 검증하고 기존 저장 경로와 배포 계약을 정한다.
- 기존 ECR push 역할과 Dockerfile별 build context를 확인해 실행 안내를 정리한다. Docker 엔진은 기동하지 않는다.
- PR #53 DDL의 파티션 프로젝션 INSERT를 격리된 합성 표·전용 S3 경로에서 시험한다. 미확정 업무 표를 임의로 변경하지 않고 시험 생성물을 정리한다.
- Bedrock의 정확한 프로필 선택과 대시보드 실행 신원·DAG 입력은 담당자 입력 대기로 구분한다. 필요한 권한 구조만 준비하며 상태값 제한·중복 승인 같은 앱 로직을 구현하지 않는다.

## 완료 확인

실제 Git 접근과 DAG 로딩, 기존 Pod 상태·노드 수, ECR/IAM 범위, Athena 쓰기·조회 및 시험 정리를 각각 기록한다. 인증 비밀과 데이터는 Git에 올리지 않는다. 동료 본인 세션 테스트·업무 이미지 실행·5분 업무 SLA는 설치 검증과 구분한다.

## 작업 결과

- Git DAG: 현재 이미지의 Git provider 0.5.0과 git을 확인하고 공개 저장소 main의 기존 DAG 경로를 실제 clone했다. 기존 bundle 이름을 유지해 GitDagBundle로 전환했다. Helm schema/render·서버 dry-run 후 기존 release를 갱신했고 추가 sidecar·PVC·ALB·노드 없이 Airflow 3개 Ready·restart 0, 두 확인용 DAG의 Git 파일 경로와 paused 상태를 확인했다. Helm 1.22 schema가 kwargs 배열을 허용하지 않아 선택적 sparse_dirs는 제외했다. 기존 probe ConfigMap은 이전 release 복구용으로 남겼다.
- projection INSERT: PR #53의 고정 DDL을 격리된 임시 표/경로로 바꿔 실제 detection-job SA에서 INSERT와 SELECT 1행을 확인했다. 추가 Glue 권한을 만들지 않았고 임시 Pod·표·빈 DB·소유 파일/결과 버전 7개를 정리했다. 업무 표·뷰는 확정하지 않았다.
- ECR: 두 저장소 PutImage/InitiateLayerUpload 허용 4건·타 저장소 거부 2건·토큰 발급 허용을 simulation으로 확인했다. 판정 context는 현재 main 기준 agent/detect, 조사 PR #54는 agent다. 업무 Dockerfile·빌드·push는 담당자 소유로 유지했다.
- dashboard-access: 독립 state로 IAM 역할/정책·Athena workgroup·Pod Identity 4개를 생성했다. namespace/SA도 준비했고 앱·노드·업무 표는 생성하지 않았다. 업무 쓰기는 reprocess_events/만 허용한다. 실제 Pod Identity·Athena SELECT 1·정답표 목록 거부, Airflow의 인증 없는 HTTP 403 응답을 확인했다. IAM simulation 18건 통과. 인증 성공이나 업무 DAG 호출은 검증하지 않았다. 임시 Pod·조회 결과를 정리했고 사후 Terraform plan은 변경 없음이다.
- Bedrock: 두 후보 프로필과 목적지 ARN을 읽기 전용으로 조회했다. 모델 담당자 확정 전에는 빈 map을 유지하는 선택형 정책을 추가했다. 실제 gold-b-access plan은 변경 없음이며 모델 호출/추가 권한은 없다. 목적지 모델은 선택 프로필 조건으로 묶고 전체 리전/모델 와일드카드를 거부한다.
- 검증: Terraform 17 roots·16 mock suites/79 plan runs 통과. 처음 검사에서 plan 시점 미확정 ID 참조가 발견돼 알려진 이름/ARN 참조로 바꾸고 재검증했다. 애플리케이션·업무 SQL·DAG 로직은 수정하지 않았다.
- 자격증명: 기존 Airflow approval 비밀번호를 dashboard/airflow-api-client Secret으로 복제하는 명령은 자동 승인 검토가 구체적인 복제 승인 없이 보관/접근 범위를 넓힌다는 이유로 거부했다. 실행되지 않았고 우회하지 않았다. Secret 없이 가능한 namespace/SA·권한·네트워크 검증만 완료했다. 사용자 명시 승인 후 이 Secret 공급을 연결한다.
- 인계: [담당자 연결표](../agent-runtime-handoff.md). 실제 업무 표 생성, 이미지 build/push, 업무 DAG 활성화·5분 SLA, 모델 선택·프로필 활성화, 승인 화면 로직·실제 DAG ID/conf는 담당자 입력 후 연결할 항목이다. 코드 작업은 별도 브랜치에 보존하며 자동 머지/자체 승인은 하지 않는다.
