mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
}
run "unchanged_repositories_by_default" {
  command = plan
  module { source = "../modules/ecr" }
  variables { name = "test-runtime" }
  assert {
    condition     = toset(keys(aws_ecr_repository.this)) == toset(["web", "was"]) && length(aws_iam_user_policy.spark_image_push) == 0
    error_message = "Spark images and IAM grants must be opt-in."
  }
}
run "spark_push_is_separate_and_scoped" {
  command = plan
  module { source = "../modules/ecr" }
  variables {
    name                      = "test-runtime"
    enable_connect_repository = true
    enable_spark_repositories = true
    spark_publisher_user_arns = ["arn:aws:iam::123456789012:user/de-ai-18"]
  }
  override_resource {
    target          = aws_ecr_repository.this["spark-base"]
    values          = { arn = "arn:aws:ecr:ap-northeast-1:123456789012:repository/test-runtime/spark-base" }
    override_during = plan
  }
  override_resource {
    target          = aws_ecr_repository.this["silver-gold-a"]
    values          = { arn = "arn:aws:ecr:ap-northeast-1:123456789012:repository/test-runtime/silver-gold-a" }
    override_during = plan
  }
  assert {
    condition = (
      toset(keys(aws_ecr_repository.this)) == toset(["web", "was", "connect", "spark-base", "silver-gold-a"]) &&
      aws_ecr_repository.this["spark-base"].image_tag_mutability == "IMMUTABLE" &&
      !aws_ecr_repository.this["silver-gold-a"].force_delete &&
      aws_iam_user_policy.spark_image_push["arn:aws:iam::123456789012:user/de-ai-18"].user == "de-ai-18" &&
      length(jsondecode(aws_iam_user_policy.spark_image_push["arn:aws:iam::123456789012:user/de-ai-18"].policy).Statement[0].Resource) == 2 &&
      !contains(jsondecode(aws_iam_user_policy.spark_image_push["arn:aws:iam::123456789012:user/de-ai-18"].policy).Statement[0].Action, "ecr:DeleteRepository")
    )
    error_message = "Preserve existing repositories and restrict developer image publishing to the two new repositories."
  }
}
run "reject_role_as_user_publisher" {
  command = plan
  module { source = "../modules/ecr" }
  variables {
    name                      = "test-runtime"
    enable_spark_repositories = true
    spark_publisher_user_arns = ["arn:aws:iam::123456789012:role/example"]
  }
  expect_failures = [var.spark_publisher_user_arns]
}
run "reject_wrong_account_publisher" {
  command = plan
  module { source = "../modules/ecr" }
  variables {
    name                      = "test-runtime"
    enable_spark_repositories = true
    spark_publisher_user_arns = ["arn:aws:iam::999999999999:user/de-ai-18"]
  }
  expect_failures = [aws_iam_user_policy.spark_image_push]
}
