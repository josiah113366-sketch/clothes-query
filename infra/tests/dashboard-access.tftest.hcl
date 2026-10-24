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
      aws_eks_pod_identity_association.dashboard.service_account == "approval-dashboard" &&
      length(aws_iam_role_policy.pipeline_status) == 0
    )
    error_message = "Approval writer must remain scoped to reprocess events, its own workgroup and dashboard identity."
  }
}
run "pipeline_status_is_opt_in_and_read_only" {
  command = plan
  module { source = "../modules/dashboard-access" }
  variables { enable_pipeline_status_reads = true }
  assert {
    condition = (
      alltrue(flatten([for s in jsondecode(aws_iam_role_policy.pipeline_status[0].policy).Statement : [for a in s.Action : contains([
        "glue:GetDatabase", "glue:GetTable", "glue:GetPartitions", "glue:GetPartition", "glue:BatchGetPartition", "s3:GetObject", "s3:ListBucket"
      ], a)]])) &&
      toset([for s in jsondecode(aws_iam_role_policy.pipeline_status[0].policy).Statement : s if s.Sid == "PipelineStatusMetadata"][0].Resource) == toset(concat([
        "arn:aws:glue:ap-northeast-1:000000000000:catalog"
        ], [for db in ["gold_b", "silver", "gold_a"] : "arn:aws:glue:ap-northeast-1:000000000000:database/${db}"], [for table in [
          "gold_b/bronze_lag_snapshots", "gold_b/topic_messages", "gold_b/payment_events", "gold_b/malformed_events", "silver/silver_runs", "gold_a/gold_runs"
      ] : "arn:aws:glue:ap-northeast-1:000000000000:table/${table}"])) &&
      contains([for s in jsondecode(aws_iam_role_policy.pipeline_status[0].policy).Statement : s if s.Sid == "PipelineStatusObjects"][0].Resource,
      "arn:aws:s3:::test-dashboard-bucket/gold_a/runtime/trade/catalog/completed/*") &&
      !strcontains(aws_iam_role_policy.pipeline_status[0].policy, "ground_truth") &&
      !strcontains(aws_iam_role_policy.pipeline_status[0].policy, "review_aspect_scores_iceberg")
    )
    error_message = "Pipeline dashboard status must grant only named metadata and completion/ledger reads, preserving source write isolation."
  }
}
run "reject_shared_results" {
  command = plan
  module { source = "../modules/dashboard-access" }
  variables { results_prefix = "athena-results/detection/" }
  expect_failures = [var.results_prefix]
}
