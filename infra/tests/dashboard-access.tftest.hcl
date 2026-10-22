mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_caller_identity" { defaults = { account_id = "000000000000" } }
}
variables {
  cluster_name = "test-cluster"
  bucket_arn   = "arn:aws:s3:::test-dashboard-bucket"
}
run "isolated_approval_writer" {
  command = plan
  module { source = "../modules/dashboard-access" }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.dashboard.policy).Statement[3].Resource == ["arn:aws:s3:::test-dashboard-bucket/gold_b/reprocess_events/*"] &&
      !contains(jsondecode(aws_iam_role_policy.dashboard.policy).Statement[3].Action, "s3:DeleteObject") &&
      jsondecode(aws_iam_role_policy.dashboard.policy).Statement[7].Effect == "Deny" &&
      aws_athena_workgroup.dashboard.configuration[0].enforce_workgroup_configuration &&
      aws_athena_workgroup.dashboard.configuration[0].bytes_scanned_cutoff_per_query == 1073741824 &&
      aws_eks_pod_identity_association.dashboard.namespace == "dashboard" &&
      aws_eks_pod_identity_association.dashboard.service_account == "approval-dashboard"
    )
    error_message = "Approval writer must remain scoped to reprocess events, its own workgroup and dashboard identity."
  }
}
run "reject_shared_results" {
  command = plan
  module { source = "../modules/dashboard-access" }
  variables { results_prefix = "athena-results/detection/" }
  expect_failures = [var.results_prefix]
}
