provider "aws" {
  region              = "ap-northeast-1"
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = "clothes-query", Environment = "dev", ManagedBy = "terraform" }
  }
}
