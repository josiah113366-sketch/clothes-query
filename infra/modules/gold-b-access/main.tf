data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  workloads = {
    detection     = "detection-job"
    investigation = "investigation-agent"
  }
  cluster_arn = "arn:${data.aws_partition.current.partition}:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
  glue_base   = "arn:${data.aws_partition.current.partition}:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}"
  bucket_name = trimprefix(var.bucket_arn, "arn:${data.aws_partition.current.partition}:s3:::")
}

resource "aws_athena_workgroup" "this" {
  for_each      = local.workloads
  name          = var.workgroup_names[each.key]
  description   = "Gold B ${each.key}: isolated S3 results and per-query scan limit"
  force_destroy = false
  state         = "ENABLED"
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff_per_query
    publish_cloudwatch_metrics_enabled = false
    requester_pays_enabled             = false
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location       = "s3://${local.bucket_name}/${var.results_prefixes[each.key]}"
      expected_bucket_owner = data.aws_caller_identity.current.account_id
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}

resource "aws_iam_role" "this" {
  for_each = local.workloads
  name     = "${var.name}-${each.value}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = {
        StringEquals = {
          "aws:RequestTag/eks-cluster-arn"            = local.cluster_arn
          "aws:RequestTag/kubernetes-namespace"       = var.namespace
          "aws:RequestTag/kubernetes-service-account" = each.value
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "this" {
  for_each = local.workloads
  name     = "gold-b-and-own-query-results"
  role     = aws_iam_role.this[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid      = "OwnWorkgroup"
        Effect   = "Allow"
        Action   = ["athena:GetWorkGroup", "athena:StartQueryExecution", "athena:StopQueryExecution", "athena:GetQueryExecution", "athena:BatchGetQueryExecution", "athena:GetQueryResults"]
        Resource = ["arn:${data.aws_partition.current.partition}:athena:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workgroup/${var.workgroup_names[each.key]}"]
      },
      {
        Sid      = "GoldBCatalogRead"
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition"]
        Resource = ["${local.glue_base}:catalog", "${local.glue_base}:database/gold_b", "${local.glue_base}:table/gold_b/*"]
      },
      {
        Sid      = "GoldBRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${var.bucket_arn}/gold_b/*"]
      },
      {
        Sid      = "OwnQueryResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = ["${var.bucket_arn}/${var.results_prefixes[each.key]}*"]
      },
      {
        Sid      = "ScopedListing"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [var.bucket_arn]
        Condition = {
          StringLike = { "s3:prefix" = concat(["gold_b/*", "${var.results_prefixes[each.key]}*"], each.key == "detection" ? [for p in var.detection_write_prefixes : "${p}*"] : []) }
        }
      },
      {
        Sid      = "BucketLocation"
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = [var.bucket_arn]
      },
      {
        Sid      = "DenyGroundTruthObjects"
        Effect   = "Deny"
        Action   = ["s3:*"]
        Resource = ["${var.bucket_arn}/ground_truth", "${var.bucket_arn}/ground_truth/*"]
      },
      {
        Sid       = "DenyGroundTruthListing"
        Effect    = "Deny"
        Action    = ["s3:ListBucket", "s3:ListBucketVersions"]
        Resource  = [var.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = ["ground_truth", "ground_truth/*"] } }
      }
      ], each.key == "detection" && length(var.detection_write_prefixes) > 0 ? [{
        Sid      = "ExplicitDetectionHistoryWrites"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload"]
        Resource = [for p in sort(tolist(var.detection_write_prefixes)) : "${var.bucket_arn}/${p}*"]
    }] : [])
  })
}

resource "aws_eks_pod_identity_association" "this" {
  for_each        = local.workloads
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = each.value
  role_arn        = aws_iam_role.this[each.key].arn
  depends_on      = [aws_iam_role_policy.this]
}
