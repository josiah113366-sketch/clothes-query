# network stack

RDS-first: `enable_nat_gateways=false`를 비공개 tfvars에 명시하면 NAT/EIP와 app 기본 인터넷 경로를 생성하지 않는다. 두 AZ subnet·route table·S3 Gateway Endpoint는 유지한다. NAT 활성화 시 이 stack의 `single_nat_gateway=true` 기본값은 첫 subnet key(a)의 NAT 한 개를 두 AZ가 공유한다. AZ별 NAT를 복원하려면 false를 명시하고 비용을 검토한다. 공유 NAT AZ 장애 시 양쪽 app subnet이 인터넷 접근을 잃고 AZ 간 전송료가 추가될 수 있다. 이후 private workload의 이미지 다운로드·AWS API/외부 통신 경로는 별도 준비해야 한다.

2개 AZ의 public/app/db subnet, 선택적 공유/AZ별 NAT, S3 Gateway Endpoint.

- 선행: 기존 bootstrap.
- backend key: `clothes-query/dev/network/terraform.tfstate`.
- 입력: `vpc_cidr`, `subnets`(서로 다른 두 AZ와 public/app/db CIDR). 범위 포함·중복·리전 AZ 검사를 수행한다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다.
- 출력: `vpc_id`, `public_subnet_ids`, `app_subnet_ids`, `db_subnet_ids`, `availability_zones`, `s3_endpoint_id`.
- 선택 `additional_s3_endpoint_actions`는 기본 빈 set이며 기존 경로 권한을 유지한다. 새 출력 `s3_endpoint_actions`를 workload-access에서 읽어 서비스 요청과 대조한다.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

NAT 2개와 EIP 2개에 지속 요금이 발생한다. app subnet은 같은 AZ의 NAT를 사용한다. DB route table에는 인터넷 기본 경로가 없다.

데이터 서비스에 multipart/버전/삭제 action이 필요하면 해당 서비스의 prefix별 IAM과 endpoint의 optional action을 함께 검토한다. endpoint 변경만으로 IAM 권한이 부여되지 않는다. 기존 저장 plan은 코드 변경 후 재생성해 최종 차이를 확인한다.
