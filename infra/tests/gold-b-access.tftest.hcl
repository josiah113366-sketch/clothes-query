mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_caller_identity" { defaults = { account_id = "000000000000" } }
}
variables {
  cluster_name        = "test-cluster"
  bucket_arn          = "arn:aws:s3:::test-gold-b-bucket"
  s3_endpoint_actions = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucket", "s3:GetBucketLocation"]
}

run "separate_roles_queries_and_results_without_business_writes" {
  command = plan
  module { source = "../modules/gold-b-access" }
  assert {
    condition = (
      length(aws_athena_workgroup.this) == 2 && length(aws_iam_role.this) == 2 &&
      length(aws_eks_pod_identity_association.this) == 2 && !output.detection_history_writes_configured &&
      aws_eks_pod_identity_association.this["detection"].service_account == "detection-job" &&
      aws_eks_pod_identity_association.this["investigation"].service_account == "investigation-agent"
    )
    error_message = "Separate operational identities are required; unknown business writes stay disabled."
  }
  assert {
    condition = alltrue([for k, wg in aws_athena_workgroup.this :
      wg.configuration[0].enforce_workgroup_configuration &&
      wg.configuration[0].bytes_scanned_cutoff_per_query == 1073741824 &&
      !wg.configuration[0].publish_cloudwatch_metrics_enabled &&
      wg.configuration[0].result_configuration[0].output_location == "s3://test-gold-b-bucket/${var.results_prefixes[k]}" &&
      wg.configuration[0].result_configuration[0].encryption_configuration[0].encryption_option == "SSE_S3"
    ])
    error_message = "Each workgroup must enforce its own encrypted result path and query cutoff without extra custom metrics."
  }
  assert {
    condition = alltrue([for k, policy in aws_iam_role_policy.this :
      jsondecode(policy.policy).Statement[0].Resource == ["arn:aws:athena:ap-northeast-1:000000000000:workgroup/clothes-query-dev-${k}"] &&
      jsondecode(policy.policy).Statement[2].Action == ["s3:GetObject"] &&
      jsondecode(policy.policy).Statement[2].Resource == ["arn:aws:s3:::test-gold-b-bucket/gold_b/*"] &&
      jsondecode(policy.policy).Statement[3].Resource == ["arn:aws:s3:::test-gold-b-bucket/${var.results_prefixes[k]}*"] &&
      jsondecode(policy.policy).Statement[6].Effect == "Deny" &&
      contains(jsondecode(policy.policy).Statement[6].Resource, "arn:aws:s3:::test-gold-b-bucket/ground_truth/*") &&
      jsondecode(policy.policy).Statement[7].Effect == "Deny" &&
      length(jsondecode(policy.policy).Statement) == 8
    ])
    error_message = "Data must be read only, results must be scoped, and ground_truth object/version/list access explicitly denied."
  }
  assert {
    condition = alltrue([for k, role in aws_iam_role.this :
      jsondecode(role.assume_role_policy).Statement[0].Principal.Service == "pods.eks.amazonaws.com" &&
      jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-namespace"] == "agent" &&
      jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-service-account"] == (k == "detection" ? "detection-job" : "investigation-agent") &&
      endswith(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/eks-cluster-arn"], ":cluster/test-cluster")
    ])
    error_message = "Trust must bind the intended cluster, namespace and individual ServiceAccount, without human trust."
  }
}

run "only_explicit_detection_history_is_writable" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables { detection_write_prefixes = ["gold_b/anomaly/", "gold_b/detection_runs/", "gold_b/reprocess_events/"] }
  assert {
    condition = (
      output.detection_history_writes_configured &&
      length(jsondecode(aws_iam_role_policy.this["investigation"].policy).Statement) == 8 &&
      toset(jsondecode(aws_iam_role_policy.this["detection"].policy).Statement[8].Resource) == toset([
        "arn:aws:s3:::test-gold-b-bucket/gold_b/anomaly/*",
        "arn:aws:s3:::test-gold-b-bucket/gold_b/detection_runs/*",
        "arn:aws:s3:::test-gold-b-bucket/gold_b/reprocess_events/*"
      ]) &&
      !contains(jsondecode(aws_iam_role_policy.this["detection"].policy).Statement[8].Action, "s3:DeleteObject")
    )
    error_message = "Future history writes must affect detection only and must not grant whole-ledger writes or deletion."
  }
}
run "reject_nested_result_paths" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables { results_prefixes = { investigation = "results/", detection = "results/detection/" } }
  expect_failures = [var.results_prefixes]
}
run "reject_results_inside_ground_truth" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables { results_prefixes = { investigation = "ground_truth/answers/", detection = "results/detection/" } }
  expect_failures = [var.results_prefixes]
}
run "reject_whole_gold_b_writes" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables { detection_write_prefixes = ["gold_b/"] }
  expect_failures = [var.detection_write_prefixes]
}
run "reject_unsupported_scan_cutoff" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables { bytes_scanned_cutoff_per_query = 1 }
  expect_failures = [var.bytes_scanned_cutoff_per_query]
}
run "reject_missing_endpoint_operation" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables { s3_endpoint_actions = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"] }
  expect_failures = [var.s3_endpoint_actions]
}
