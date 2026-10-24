mock_provider "aws" {}
run "review_queries_are_driver_only_and_iceberg_is_read_only" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    enabled              = true
    namespace            = "pipelines"
    enable_review_access = true
  }
  assert {
    condition = (
      toset(keys(aws_iam_role_policy_attachment.review_s3)) == toset(["driver", "executor"]) &&
      aws_iam_role_policy_attachment.review_driver[0].role == aws_iam_role.this["driver"].name &&
      !strcontains(aws_iam_policy.review_s3[0].policy, "athena:") &&
      !strcontains(aws_iam_policy.review_s3[0].policy, "review_aspect_scores_iceberg") &&
      !strcontains(aws_iam_policy.review_s3[0].policy, "bronze_v2/reviews") &&
      [for s in jsondecode(aws_iam_policy.review_driver[0].policy).Statement : s if s.Sid == "ReadOnlyScoreIceberg"][0].Action == ["s3:GetObject"] &&
      !strcontains(aws_iam_policy.review_driver[0].policy, "glue:UpdateTable") &&
      !strcontains(aws_iam_policy.review_driver[0].policy, "glue:CreateTable") &&
      alltrue([for s in jsondecode(aws_iam_policy.review_s3[0].policy).Statement :
        !contains(s.Action, "s3:DeleteObject") || alltrue([for r in s.Resource : strcontains(r, "/__magic_job-")])
      ])
    )
    error_message = "Only the Driver may query the latest score view, with read-only Iceberg and isolated review outputs."
  }
}
run "funnel_access_is_opt_in_and_publication_driver_only" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    enabled                 = true
    namespace               = "pipelines"
    enable_funnel_access    = true
    funnel_rollback_run_ids = ["funnels-fixed-test"]
  }
  assert {
    condition = (
      toset(keys(aws_iam_role_policy.funnel_s3)) == toset(["driver", "executor"]) &&
      aws_iam_role_policy.funnel_glue[0].role == aws_iam_role.this["driver"].name &&
      !strcontains(aws_iam_role_policy.funnel_glue[0].policy, "CreateTable") &&
      !strcontains(aws_iam_role_policy.funnel_glue[0].policy, "UpdateTable") &&
      toset([for s in jsondecode(aws_iam_role_policy.funnel_s3["driver"].policy).Statement : s if s.Sid == "ClickstreamRead"][0].Resource) == toset(["arn:aws:s3:::test-trade-bucket/bronze_v2/clickstream/*"]) &&
      toset([for s in jsondecode(aws_iam_role_policy.funnel_s3["driver"].policy).Statement : s if s.Sid == "ApprovedFunnelParquetRollback"][0].Resource) == toset([
        "arn:aws:s3:::test-trade-bucket/silver/runtime/trade/runs/funnels-fixed-test/*/part-*.parquet",
        "arn:aws:s3:::test-trade-bucket/silver/runtime/clicks/runs/funnels-fixed-test/*/part-*.parquet",
        "arn:aws:s3:::test-trade-bucket/gold_a/runtime/funnels/runs/funnels-fixed-test/*/part-*.parquet"
      ]) &&
      alltrue([for s in jsondecode(aws_iam_role_policy.funnel_s3["executor"].policy).Statement :
        !contains(s.Action, "s3:DeleteObject") || alltrue([for r in s.Resource : strcontains(r, "/__magic_job-") || strcontains(r, "/runs/funnels-fixed-test/")])
      ]) &&
      !strcontains(aws_iam_role_policy.funnel_s3["driver"].policy, "ground_truth") &&
      !strcontains(aws_iam_role_policy.funnel_s3["driver"].policy, "reviews/")
    )
    error_message = "Funnel permissions must preserve separate roles, exact input/output roots and selected-run cleanup only."
  }
}
run "trade_publication_is_driver_only_and_r6_is_read_only" {
  command = plan
  module { source = "../modules/spark-access" }
  variables {
    enabled                  = true
    namespace                = "pipelines"
    enable_trade_publication = true
  }
  assert {
    condition = (
      length(aws_iam_role_policy.publication) == 1 && length(aws_iam_role_policy.r6_reader) == 1 &&
      toset(keys(aws_iam_role_policy.bronze_v2)) == toset(["driver", "executor"]) &&
      aws_iam_role_policy.r6_reader[0].role == "clothes-query-dev-detection-job" &&
      [for s in jsondecode(aws_iam_role_policy.publication[0].policy).Statement : s if s.Sid == "RegisterRunPartitions"][0].Action == ["glue:CreatePartition"] &&
      !strcontains(aws_iam_role_policy.publication[0].policy, "CreateTable") &&
      !strcontains(aws_iam_role_policy.publication[0].policy, "DeleteObject") &&
      !strcontains(aws_iam_role_policy.publication[0].policy, "ground_truth") &&
      !strcontains(aws_iam_role_policy.publication[0].policy, "agent/") &&
      alltrue(flatten([for s in jsondecode(aws_iam_role_policy.r6_reader[0].policy).Statement : [for a in s.Action : !strcontains(a, "Put") && !strcontains(a, "Create") && !strcontains(a, "Delete")]]))
    )
    error_message = "Only the driver may publish; R6 receives scoped read-only Silver access."
  }
}
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
    condition     = length(aws_iam_role.this) == 0 && length(aws_eks_pod_identity_association.this) == 0 && length(aws_iam_role_policy.funnel_s3) == 0 && length(aws_iam_role_policy.funnel_glue) == 0
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
