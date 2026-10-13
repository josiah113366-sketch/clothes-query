mock_provider "aws" {}

variables { name = "test-ecr" }

run "existing_repositories_unchanged_by_default" {
  command = plan
  module { source = "../modules/ecr" }
  assert {
    condition     = toset(keys(aws_ecr_repository.this)) == toset(["web", "was"]) && output.connect_publisher_policy == null
    error_message = "Default must preserve WEB/WAS resource keys and not add a Connect policy."
  }
  assert {
    condition     = aws_ecr_repository.this["web"].name == "test-ecr/web" && aws_ecr_repository.this["was"].name == "test-ecr/was"
    error_message = "Existing repository names must not change."
  }
}

run "connect_is_separate_and_protected" {
  command = plan
  module { source = "../modules/ecr" }
  variables { enable_connect_repository = true }
  override_resource {
    target          = aws_ecr_repository.this["connect"]
    values          = { arn = "mock-connect-repository-arn" }
    override_during = plan
  }
  assert {
    condition = (
      toset(keys(aws_ecr_repository.this)) == toset(["web", "was", "connect"]) &&
      aws_ecr_repository.this["connect"].name == "test-ecr/connect" &&
      alltrue([for r in aws_ecr_repository.this : r.image_tag_mutability == "IMMUTABLE" && !r.force_delete && one(r.image_scanning_configuration).scan_on_push && one(r.encryption_configuration).encryption_type == "AES256"])
    )
    error_message = "Connect must be additive and retain immutable tags, scanning, encryption and deletion protection."
  }
  assert {
    condition = (
      jsondecode(output.connect_publisher_policy).Statement[0].Resource == "mock-connect-repository-arn" &&
      toset(jsondecode(output.connect_publisher_policy).Statement[0].Action) == toset(["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"]) &&
      jsondecode(output.connect_publisher_policy).Statement[1].Resource == "*" &&
      toset(jsondecode(output.connect_publisher_policy).Statement[1].Action) == toset(["ecr:GetAuthorizationToken"])
    )
    error_message = "Push permissions must target only Connect; only ECR token authentication can use wildcard resource."
  }
}
