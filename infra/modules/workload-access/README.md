# workload-access module

확정된 서비스별 namespace/ServiceAccount와 S3 prefix·object action을 받아 IAM 역할·정책 및 EKS Pod Identity association을 만든다. `bindings = {}`가 기본이며 이때 리소스를 만들지 않는다. 기존 WAS 역할은 이 모듈로 이동하지 않는다.

## 입력과 출력

| 입력 | 의미 |
|---|---|
| `name` | 역할 이름 접두사. binding key와 합쳐 IAM 이름 길이를 제한 |
| `cluster_name` | association을 만들 기존 EKS 클러스터 |
| `bucket_arn` | 기존 데이터 S3 버킷. state 버킷을 넣지 않음 |
| `s3_endpoint_actions` | network state의 endpoint 허용 작업. 기본은 기존 Get/Put/List/위치 조회 |
| `bindings` | 서비스별 namespace, ServiceAccount, `s3_access = { "prefix/" = ["s3:GetObject", ...] }` |

각 binding의 선택 항목 `s3_directory_reads`는 S3A가 폴더 경로 자체를 HEAD하는 경우에 사용한다. 예를 들어 `gold_b/_checkpoints/streaming_ingest`를 넣으면 이 정확한 객체의 GetObject와 같은 값의 ListBucket prefix 조건만 추가한다. 해당 경로에 `/`를 붙인 prefix가 이미 `s3_access`에 있고 GetObject도 허용돼야 한다. 기본값은 빈 집합이며 부모·형제 경로의 접근이나 폴더 자체 쓰기·삭제를 자동 허용하지 않는다.

출력은 `service_accounts` 및 민감 표시된 `role_arns`다. 타입·검증·지원 action은 [variables.tf](variables.tf), 실제 정책은 [main.tf](main.tf)를 참고한다. [호출 스택](../../stacks/workload-access/README.md)에서 사용한다.

## 관리 경계

- Namespace·ServiceAccount·워크로드는 각 실행 환경의 담당자가 만든다. 이 모듈은 Kubernetes 리소스를 중복 생성하지 않는다.
- 동일 namespace/ServiceAccount를 다른 role association이나 기존 앱 모듈과 중복 관리하지 않는다.
- 각 서비스에는 요청된 object action만 준다. bucket List는 명시한 prefix로 제한하고 GetBucketLocation을 제공한다. wildcard action·prefix와 버킷 루트 접근 요청은 거부한다.
- DeleteObject는 명시적으로 요청한 prefix에만 허용할 수 있다. 읽기·쓰기 권한에서 자동으로 따라오지 않는다. 삭제가 필요한 checkpoint/commit 동작은 서비스 담당자가 보존 정책과 함께 검토한다.
- multipart 업로드·버전 읽기 등은 필요한 action을 명시한다. 이 설정을 모든 SDK/파일시스템의 전체 호환 권한으로 간주하지 않는다. 추가 bucket 작업이 필요하면 별도 정책 검토가 필요하다.
- 요청 action이 network의 S3 endpoint 정책에서 허용되지 않으면 plan 입력을 거부한다. optional action을 쓰려면 network의 `additional_s3_endpoint_actions`부터 명시적으로 준비하고 최신 output을 반영한다. endpoint 허용은 IAM 권한 부여를 대신하지 않는다.
- Secrets Manager·DB·Kafka·쿼리 엔진 권한을 자동 부여하지 않는다. S3 읽기 권한은 SQL 조회 서비스 구현을 대신하지 않는다.

Pod Identity의 기본 trust는 `pods.eks.amazonaws.com`의 AssumeRole/TagSession을 사용하고 namespace·ServiceAccount 조건으로 제한한다. 앱은 Pod Identity를 지원하는 SDK 자격증명 체인을 사용해야 한다. [AWS Pod Identity 안내](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-role.html)

object action과 실제 API 작업의 대응은 서비스 담당자와 확인한다. [AWS S3 권한 안내](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html)

## 검증과 운영

mock plan은 역할 분리·prefix·action·trust/association 일치와 잘못된 입력을 확인한다. 실제 AWS 권한과 기존 bucket/endpoint/KMS 정책은 배포 환경에서 검증한다. 역할을 제거하거나 권한을 좁히면 실행 중 서비스의 접근에 영향을 줄 수 있다. 실제 association·리소스 소유권과 최종 plan을 확인한 뒤 변경한다.
