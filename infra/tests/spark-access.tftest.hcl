mock_provider "aws" {}
variables {
  cluster_name = "test-cluster"
  bucket_arn   = "arn:aws:s3:::test-trade-bucket"
  s3_endpoint_actions = [
    "s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation",
    "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
  ]
}
run "no_identity_before_namespace_confirmation" {
  command = plan
  module { source = "../modules/spark-access" }
  assert {
    condition     = length(aws_iam_role.this) == 0 && length(aws_eks_pod_identity_association.this) == 0
    error_message = "Unconfirmed namespace must create no execution roles or associations."
  }
}
run "separate_execution_roles_and_magic_cleanup" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    enabled   = true
    namespace = "pipelines"
  }
  assert {
    condition = (
      toset(keys(aws_iam_role.this)) == toset(["driver", "executor"]) &&
      aws_eks_pod_identity_association.this["driver"].service_account == "silver-gold-a-driver" &&
      aws_eks_pod_identity_association.this["executor"].service_account == "silver-gold-a-executor" &&
      jsondecode(aws_iam_role.this["driver"].assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-namespace"] == "pipelines" &&
      jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement[0].Action == ["s3:GetObject"] &&
      contains(jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement[1].Action, "s3:AbortMultipartUpload") &&
      contains(jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement[1].Action, "s3:ListMultipartUploadParts") &&
      !contains(jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement[1].Action, "s3:DeleteObject") &&
      alltrue([for p in jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement[2].Resource : endswith(p, "/runs/*/*/__magic_job-*/*")]) &&
      length(jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement) == 5
    )
    error_message = "Only Driver/Executor get scoped S3 roles; final output deletion and bucket-wide multipart metadata listing are not default grants."
  }
}
run "reject_enabled_without_namespace" {
  command = plan
  module { source = "../modules/spark-access" }
  variables { enabled = true }
  expect_failures = [var.namespace]
}
run "reject_unrelated_or_traversal_prefixes" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    read_prefixes   = ["ground_truth/"]
    output_prefixes = ["silver/runtime/trade/../other/"]
  }
  expect_failures = [var.read_prefixes, var.output_prefixes]
}
run "reject_missing_endpoint_transport" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    enabled             = true
    namespace           = "pipelines"
    s3_endpoint_actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"]
  }
  expect_failures = [aws_iam_role.this]
}
run "reference_snapshots_and_approved_rollback_runs_only" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    enabled                        = true
    namespace                      = "pipelines"
    allow_bucket_multipart_listing = true
    rollback_run_ids               = ["trade-fixed-normal-20261023"]
    reference_object_arns          = ["arn:aws:s3:::hm-ecommerce-data/seed_v2/product_design/product_design.parquet"]
    s3_endpoint_actions = [
      "s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation", "s3:DeleteObject",
      "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:ListBucketMultipartUploads"
    ]
  }
  assert {
    condition = (
      [for s in jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement : s if s.Sid == "ProductReferenceObjectsReadOnly"][0].Action == ["s3:GetObject"] &&
      alltrue([for p in [for s in jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement : s if s.Sid == "ApprovedRunParquetRollback"][0].Resource : strcontains(p, "/runs/trade-fixed-normal-20261023/") && endswith(p, "/part-*.parquet")]) &&
      [for s in jsondecode(aws_iam_role_policy.s3["driver"].policy).Statement : s if s.Sid == "OptionalMultipartMetadataListing"][0].Action == ["s3:ListBucketMultipartUploads"]
    )
    error_message = "Read only named reference objects and permit rollback only for approved runs' Parquet parts."
  }
}
run "reject_wildcard_rollback_and_unconfirmed_reference" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    rollback_run_ids      = ["*"]
    reference_object_arns = ["arn:aws:s3:::hm-ecommerce-data/*"]
  }
  expect_failures = [var.rollback_run_ids, var.reference_object_arns]
}
