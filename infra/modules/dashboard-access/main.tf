data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account    = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  glue       = "arn:${local.partition}:glue:ap-northeast-1:${local.account}"
  bucket     = trimprefix(var.bucket_arn, "arn:${local.partition}:s3:::")
  cluster    = "arn:${local.partition}:eks:ap-northeast-1:${local.account}:cluster/${var.cluster_name}"
  data_paths = ["gold_b/anomaly/", "gold_b/reprocess_events/", "agent/investigation_reports/", var.model_registry_prefix]
}

resource "aws_athena_workgroup" "dashboard" {
  name          = var.workgroup_name
  force_destroy = false
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff_per_query
    publish_cloudwatch_metrics_enabled = false
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location       = "s3://${local.bucket}/${var.results_prefix}"
      expected_bucket_owner = local.account
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}

resource "aws_iam_role" "dashboard" {
  name = "clothes-query-dev-approval-dashboard"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = { StringEquals = {
        "aws:RequestTag/eks-cluster-arn"            = local.cluster
        "aws:RequestTag/kubernetes-namespace"       = var.namespace
        "aws:RequestTag/kubernetes-service-account" = var.service_account
      } }
    }]
  })
}

resource "aws_iam_role_policy" "dashboard" {
  name = "dashboard-reads-and-reprocess-event-writes"
  role = aws_iam_role.dashboard.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "OwnWorkgroup"
        Effect   = "Allow"
        Action   = ["athena:GetWorkGroup", "athena:StartQueryExecution", "athena:StopQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
        Resource = ["arn:${local.partition}:athena:ap-northeast-1:${local.account}:workgroup/${var.workgroup_name}"]
      },
      {
        Sid      = "ViewAndSourceMetadata"
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions", "glue:GetPartition", "glue:BatchGetPartition"]
        Resource = concat(["${local.glue}:catalog", "${local.glue}:database/gold_b", "${local.glue}:database/agent"], [for t in ["gold_b/anomaly_current", "gold_b/anomaly", "gold_b/reprocess_events", "agent/investigation_reports"] : "${local.glue}:table/${t}"])
      },
      {
        Sid      = "DashboardSourceReads"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [for p in local.data_paths : "${var.bucket_arn}/${p}*"]
      },
      {
        Sid      = "ReprocessEventWrites"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = ["${var.bucket_arn}/gold_b/reprocess_events/*"]
      },
      {
        Sid      = "OwnQueryResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = ["${var.bucket_arn}/${var.results_prefix}*"]
      },
      {
        Sid       = "ScopedListing"
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = [var.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = concat([for p in local.data_paths : "${p}*"], ["${var.results_prefix}*"]) } }
      },
      { Sid = "BucketLocation", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = [var.bucket_arn] },
      { Sid = "DenyGroundTruthObjects", Effect = "Deny", Action = ["s3:*"], Resource = ["${var.bucket_arn}/ground_truth", "${var.bucket_arn}/ground_truth/*"] },
      {
        Sid       = "DenyGroundTruthListing"
        Effect    = "Deny"
        Action    = ["s3:ListBucket", "s3:ListBucketVersions"]
        Resource  = [var.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = ["ground_truth", "ground_truth/*"] } }
      }
    ]
  })
}

resource "aws_eks_pod_identity_association" "dashboard" {
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = var.service_account
  role_arn        = aws_iam_role.dashboard.arn
  depends_on      = [aws_iam_role_policy.dashboard]
}
