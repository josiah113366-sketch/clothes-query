mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "000000000000" } }
}
run "collector_can_only_write_its_snapshot_prefix" {
  command = plan
  module { source = "../modules/bronze-lag-collector" }
  variables {
    cluster_name = "test-cluster"
    bucket_arn   = "arn:aws:s3:::test-bucket"
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.this.policy).Statement[0].Action == ["s3:PutObject"] &&
      jsondecode(aws_iam_role_policy.this.policy).Statement[0].Resource == ["arn:aws:s3:::test-bucket/gold_b/bronze_lag_snapshots/*"] &&
      aws_eks_pod_identity_association.this.namespace == "pipelines" &&
      aws_eks_pod_identity_association.this.service_account == "gold-b-lag-collector" &&
      aws_ecr_repository.this.image_tag_mutability == "IMMUTABLE"
    )
    error_message = "Collector needs only its own output writes and matching Pod Identity."
  }
}
