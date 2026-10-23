# S3 backend. backend 블록에는 변수를 쓸 수 없어서 bucket/region 은 여기에 적지 않고 init 때 넘긴다.
# 추적되는 deployment.backend.hcl(infra/DEPLOYMENT_CONFIG.md)에 bucket, region 이 있고 init 때 -backend-config 로 넘긴다.
# key 는 스택마다 반드시 달라야 한다(같으면 두 스택이 state 를 공유해 서로의 리소스를 지우려 한다).
terraform {
  backend "s3" {
    key          = "clothes-query/dev/sagemaker-review-score/terraform.tfstate"
    use_lockfile = true # S3 네이티브 잠금(Terraform 1.10+). DynamoDB 불필요
    encrypt      = true
  }
}
