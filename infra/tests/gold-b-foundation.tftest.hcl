mock_provider "aws" {}

run "gold_b_repository_does_not_widen_other_publishers" {
  command = plan
  module { source = "../modules/ecr" }
  variables {
    name                      = "test-data"
    enable_connect_repository = true
    enable_spark_repositories = true
    enable_gold_b_repository  = true
    spark_publisher_user_arns = []
  }
  assert {
    condition = (
      toset(keys(aws_ecr_repository.this)) == toset(["web", "was", "connect", "spark-base", "silver-gold-a", "gold-b"]) &&
      aws_ecr_repository.this["gold-b"].image_tag_mutability == "IMMUTABLE" &&
      !aws_ecr_repository.this["gold-b"].force_delete &&
      length(aws_iam_user_policy.spark_image_push) == 0
    )
    error_message = "Preparing Gold B must preserve repository addresses and never infer a publishing principal."
  }
}
