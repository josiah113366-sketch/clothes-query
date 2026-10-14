> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# network stack

2개 AZ의 public/app/db subnet, AZ별 NAT, S3 Gateway Endpoint.

- 선행: 기존 bootstrap.
- backend key: `clothes-query/dev/network/terraform.tfstate`.
- 입력: `vpc_cidr`, `subnets`(서로 다른 두 AZ와 public/app/db CIDR). 범위 포함·중복·리전 AZ 검사를 수행한다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다.
- 출력: `vpc_id`, `public_subnet_ids`, `app_subnet_ids`, `db_subnet_ids`, `availability_zones`, `s3_endpoint_id`.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

NAT 2개와 EIP 2개에 지속 요금이 발생한다. app subnet은 같은 AZ의 NAT를 사용한다. DB route table에는 인터넷 기본 경로가 없다.
