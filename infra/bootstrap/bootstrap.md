# bootstrap

## 목적

모든 스택의 Terraform state를 저장할 S3 버킷을 만든다.

- 버킷 이름: `clothes-query-tfstate-<AWS계정ID>` (리전 `ap-northeast-1`)
- 버저닝 활성화, SSE-S3(AES256) 암호화, 퍼블릭 액세스 전체 차단

## 의존 스택

없음. 가장 먼저 apply하는 스택이다.

## state

이 스택만 **local state**를 쓴다 (`backend.tf` 없음). state 버킷이 아직 없는 상태에서 그 버킷을 만들기 때문이다.
`terraform.tfstate`는 `.gitignore` 대상이라 커밋되지 않으므로, apply한 PC에만 남는다.
필요하면 apply 후 `backend.tf`를 추가하고 `terraform init -migrate-state`로 버킷에 옮긴다
(key: `clothes-query/dev/bootstrap/terraform.tfstate`).

## 실행 방법

최초 1회만 apply한다.

```bash
cd infra/bootstrap
terraform init
terraform fmt
terraform validate
terraform plan
terraform apply   # 사용자가 직접 실행
```

## 주요 output

| 이름 | 설명 |
|---|---|
| `tfstate_bucket_name` | state 버킷 이름. 각 스택 `backend.tf`의 `bucket`에 그대로 적는다 |
| `tfstate_bucket_arn` | state 버킷 ARN |
| `tfstate_bucket_region` | state 버킷 리전 |

## destroy 주의점

- 버킷에 `prevent_destroy = true`가 걸려 있어 `terraform destroy`는 에러로 멈춘다.
- 이 버킷을 지우면 모든 스택의 state가 사라진다. 다른 스택을 전부 destroy한 뒤 **가장 마지막**에 지운다.
- 지울 때는 `prevent_destroy`를 코드에서 제거하고, 버저닝된 객체(이전 버전 포함)를 모두 비운 뒤 destroy한다.
