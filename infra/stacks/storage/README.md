# storage stack

## 사용자 승인 배포 결과 (2026-10-14)

`clothes-query-datalake`를 도쿄에 생성했다. 저장한 plan의 5 create / 0 change / 0 destroy를 적용하고 후속 plan 종료 코드 0(변경 없음)을 확인했다. 버저닝 Enabled, AES256 암호화, 퍼블릭 액세스 차단 4개 모두 활성, bucket policy 공개 아님, 비보안 전송 거부를 AWS 조회로 확인했다. 내부 객체·경로는 만들지 않았다.

state는 기존 state 버킷의 `clothes-query/dev/storage/terraform.tfstate`에 저장됐고 AES256·version ID·lock 해제를 확인했다. 실제 계정 입력과 plan은 Git 제외 파일에만 보관한다. 네트워크/EKS/RDS/Kafka는 이번 apply에 포함하지 않았다.

state와 분리된 데이터 S3, 버저닝·암호화·공개 차단·TLS 정책.

- 선행: 기존 bootstrap.
- backend key: `clothes-query/dev/storage/terraform.tfstate`.
- 입력: `bucket_name`: 기존 버킷과 충돌하지 않는 승인된 이름. 기존 버킷 재사용은 관리 state 확인과 별도 import 계획이 필요하다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다.
- 출력: `bucket_name`, `bucket_arn`.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

force_destroy=false, prevent_destroy=true. 버전 및 객체를 자동 만료시키지 않으므로 보관량에 따라 요금이 누적된다. 수명주기는 데이터 보존 합의 후 추가한다.
