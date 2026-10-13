# network module

2개 AZ의 public/app/db subnet, AZ별 NAT, S3 Gateway Endpoint를 관리한다.

## 입력과 출력

- 배포 사양: `vpc_cidr`, `subnets`(서로 다른 두 AZ와 public/app/db CIDR). 범위 포함·중복·리전 AZ 검사를 수행한다.
- 연결 입력: `name`, `region`. [호출 스택](../../stacks/network/main.tf)에서 연결한다.
- 출력: `vpc_id`, `public_subnet_ids`, `app_subnet_ids`, `db_subnet_ids`, `availability_zones`, `s3_endpoint_id`.
- 선택 `additional_s3_endpoint_actions`는 기본 빈 set. 출력 `s3_endpoint_actions`는 기본 작업과 명시된 optional action을 포함하며 데이터 workload의 요청과 대조한다.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[network 스택](../../stacks/network/README.md)에서 실행한다. NAT 2개와 EIP 2개에 지속 요금이 발생한다. app subnet은 같은 AZ의 NAT를 사용한다. DB route table에는 인터넷 기본 경로가 없다.

S3 endpoint 정책의 Resource/Principal 와일드카드는 ECR 이미지 layer의 AWS 소유 S3 bucket 접근도 통과시키기 위한 경로 정책이다. 앱의 허용 범위는 Pod Identity IAM 및 bucket 정책으로 제한한다. endpoint가 IAM 허가를 대체하지 않는다.

기본 GetObject/PutObject/ListBucket/GetBucketLocation은 유지한다. 버전 읽기·삭제·multipart 정리가 필요한 서비스만 optional action을 명시적으로 추가한다. 이 확장은 경로 허용이며 실제 prefix별 IAM 권한은 별도다. wildcard action은 받지 않는다. [AWS endpoint 정책 안내](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html)
