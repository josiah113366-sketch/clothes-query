# S3 backend. 버킷 이름에 계정 ID 가 들어가 공개 저장소에 쓸 수 없으므로 bucket/region 은 여기에 적지 않는다.
# 비공개 파일 deployment.backend.hcl(Git 제외)에 bucket, region 을 두고 init 때 -backend-config 로 넘긴다.
# key 는 스택마다 반드시 달라야 한다(같으면 두 스택이 state 를 공유해 서로의 리소스를 지우려 한다).
terraform {
  backend "s3" {
    key          = "clothes-query/dev/athena-review-score/terraform.tfstate"
    use_lockfile = true # S3 네이티브 잠금(Terraform 1.10+). DynamoDB 불필요
    encrypt      = true
  }
}
