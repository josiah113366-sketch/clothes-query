mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_region" { defaults = { region = "ap-northeast-1" } }
  mock_data "aws_caller_identity" { defaults = { account_id = "000000000000" } }
}

run "explicit_trust_and_namespace_group_only" {
  command = plan
  module { source = "../modules/agent-development-access" }
  variables {
    name                   = "test-agent"
    cluster_name           = "test-cluster"
    trusted_principal_arns = ["arn:aws:iam::000000000000:user/test-developer"]
  }
  override_resource {
    target          = aws_ecr_repository.agent["detection-job"]
    values          = { arn = "arn:aws:ecr:ap-northeast-1:000000000000:repository/test-agent/detection-job" }
    override_during = plan
  }
  override_resource {
    target          = aws_ecr_repository.agent["investigation-agent"]
    values          = { arn = "arn:aws:ecr:ap-northeast-1:000000000000:repository/test-agent/investigation-agent" }
    override_during = plan
  }
  assert {
    condition = (
      jsondecode(aws_iam_role.developer.assume_role_policy).Statement[0].Principal.AWS == ["arn:aws:iam::000000000000:user/test-developer"] &&
      toset(aws_eks_access_entry.developer.kubernetes_groups) == toset(["clothes-query:agent-developers"]) &&
      aws_eks_access_entry.developer.type == "STANDARD"
    )
    error_message = "Trust explicit users only and map to the development group, never system:masters."
  }
  assert {
    condition = (
      toset(keys(aws_ecr_repository.agent)) == toset(["detection-job", "investigation-agent"]) &&
      alltrue([for r in aws_ecr_repository.agent : r.image_tag_mutability == "IMMUTABLE" && !r.force_delete]) &&
      jsondecode(aws_iam_role_policy.developer.policy).Statement[0].Resource == ["arn:aws:eks:ap-northeast-1:000000000000:cluster/test-cluster"] &&
      jsondecode(aws_iam_role_policy.developer.policy).Statement[1].Action == ["ecr:GetAuthorizationToken"] &&
      jsondecode(aws_iam_role_policy.developer.policy).Statement[1].Resource == "*" &&
      toset(jsondecode(aws_iam_role_policy.developer.policy).Statement[2].Resource) == toset(["arn:aws:ecr:ap-northeast-1:000000000000:repository/test-agent/detection-job", "arn:aws:ecr:ap-northeast-1:000000000000:repository/test-agent/investigation-agent"])
    )
    error_message = "Limit publishing to agent repositories and Describe to the project cluster."
  }
}
