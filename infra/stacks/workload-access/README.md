# workload-access stack

데이터 처리/조회 서비스의 S3 접근 역할을 기존 EKS와 데이터 S3에 연결한다. 기본 `bindings = {}`이며 승인된 서비스 입력이 없으면 IAM 역할·정책·association을 만들지 않는다. 실제 plan은 빈 binding에서도 선행 remote state를 읽는다.

- 선행: bootstrap 상태 확인, network·eks·storage 배포 및 해당 state. network에는 이번 코드의 `s3_endpoint_actions` output이 있어야 한다.
- backend key: `clothes-query/dev/workload-access/terraform.tfstate`. 기존 state key와 공유하지 않는다.
- 필수 비공개 입력: `TF_VAR_expected_account_id`, `TF_VAR_state_bucket`, `deployment.backend.hcl`의 기존 bucket/region.
- 서비스 입력: [terraform.tfvars.example](terraform.tfvars.example). 예제 namespace·prefix·서비스 이름은 실제 배포 결정이 아니다.
- 출력: `service_accounts`, 민감 표시된 `role_arns`.

## 준비와 실행

[전체 안내](../../IMPLEMENTATION.md)와 [데이터 경로 준비](../../../docs/design/infra/data-path-readiness.md)를 먼저 읽는다. 예제를 Git 제외 `deployment.local.tfvars`로 복사해 서비스 담당자의 명시적 namespace/ServiceAccount·prefix·action 입력을 반영한다. 같은 association이 다른 state·관리 도구에 없는지 확인한다.

정적 검사는 backend 없이 init·validate를 수행한다. 실제 backend 초기화·plan은 기존 계정/state 확인 후에만 진행하고 apply는 사용자가 검토 후 실행한다. 워크로드는 이 스택의 성공만으로 배포되지 않으며, 해당 namespace/ServiceAccount와 SDK·이미지·설정 공급은 실행 환경 담당자의 작업이다.

기존 network state에 새 output이 없으면 최신 network 코드의 plan을 검토해 먼저 반영해야 한다. 예제의 AbortMultipartUpload 등은 network의 명시적 optional action 허용도 필요하다. IAM만 추가해 경로에서 차단되는 구성을 입력 검증으로 방지한다. 과거 저장한 plan은 변경된 코드의 최종 plan으로 재생성한다.

## 검증과 삭제

서비스별 전용 검증 경로에서 허용 작업 성공과 다른 prefix 접근 거부를 확인한다. 삭제 권한은 명시한 경우만 부여하며 테스트 객체 정리는 담당자가 승인한 절차로 수행한다. 역할/association 삭제 전 해당 서비스를 확인한다. 기존 WAS 역할·데이터 버킷·state를 이 스택에서 관리하거나 이동하지 않는다.
