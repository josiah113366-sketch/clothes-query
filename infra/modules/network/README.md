# network module

2개 AZ의 public/app/db subnet, AZ별 NAT, S3 Gateway Endpoint를 관리한다.

## 입력과 출력

- 배포 사양: `vpc_cidr`, `subnets`(서로 다른 두 AZ와 public/app/db CIDR). 범위 포함·중복·리전 AZ 검사를 수행한다.
- 연결 입력: `name`, `region`. [호출 스택](../../stacks/network/main.tf)에서 연결한다.
- 출력: `vpc_id`, `public_subnet_ids`, `app_subnet_ids`, `db_subnet_ids`, `availability_zones`, `s3_endpoint_id`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[network 스택](../../stacks/network/README.md)에서 실행한다. NAT 2개와 EIP 2개에 지속 요금이 발생한다. app subnet은 같은 AZ의 NAT를 사용한다. DB route table에는 인터넷 기본 경로가 없다.

S3 endpoint 정책의 Resource/Principal 와일드카드는 ECR 이미지 layer의 AWS 소유 S3 bucket 접근도 통과시키기 위한 경로 정책이다. 앱의 허용 범위는 Pod Identity IAM 및 bucket 정책으로 제한한다. endpoint가 IAM 허가를 대체하지 않는다.
