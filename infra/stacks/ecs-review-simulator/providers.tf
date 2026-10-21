provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    # Component: ecs-review-simulator cost allocation tag (monthly budget filter)
    tags = { Project = "clothes-query", Environment = "dev", ManagedBy = "terraform", Component = "ecs-review-simulator" }
  }
}
