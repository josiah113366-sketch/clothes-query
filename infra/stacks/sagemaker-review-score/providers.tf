provider "aws" {
  region = var.aws_region
  # 잘못된 AWS 계정에 apply 하는 사고를 막는다. 계정 ID 는 공유 배포 설정 deployment.auto.tfvars.json(infra/DEPLOYMENT_CONFIG.md)으로 자동 로드된다.
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    # Component: 비용 할당 태그(월 예산 필터). 팀 규칙: Component=<스택 이름>
    # 주의: default_tags 는 Terraform 이 만든 리소스에만 붙는다. 스크립트가 만드는 Processing Job 은 SSM 설정의 tags 로 따로 붙인다.
    tags = { Project = "clothes-query", Environment = "dev", ManagedBy = "terraform", Component = "sagemaker-review-score" }
  }
}
