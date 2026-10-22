provider "aws" {
  region = var.aws_region
  # 잘못된 AWS 계정에 apply 하는 사고를 막는다. 계정 ID 는 환경변수 TF_VAR_expected_account_id 로만 넘긴다(저장소에 두지 않음).
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    # Component: 비용 할당 태그. 팀 규칙: Component=<스택 이름>
    tags = { Project = "clothes-query", Environment = "dev", ManagedBy = "terraform", Component = "athena-review-score" }
  }
}
