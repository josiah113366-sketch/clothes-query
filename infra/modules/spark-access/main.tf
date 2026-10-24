data "aws_caller_identity" "current" {}

locals {
  actors         = var.enabled ? toset(["driver", "executor"]) : toset([])
  object_actions = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
  required_actions = concat(local.object_actions, ["s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation"],
  var.allow_bucket_multipart_listing ? ["s3:ListBucketMultipartUploads"] : [])
  # Temporary objects plus explicitly approved validation runs; never whole output roots.
  magic_patterns = [for p in sort(tolist(var.output_prefixes)) : "${p}runs/*/*/__magic_job-*/*"]
  rollback_patterns = flatten([for p in sort(tolist(var.output_prefixes)) : [
    for run_id in sort(tolist(var.rollback_run_ids)) : "${p}runs/${run_id}/*/part-*.parquet"
  ]])
  reference_keys = [for arn in sort(tolist(var.reference_object_arns)) : trimprefix(arn, "arn:aws:s3:::hm-ecommerce-data/")]
  publish_trade  = var.enabled && var.enable_trade_publication
  bronze_v2      = ["bronze_v2/orders/", "bronze_v2/order-items/", "bronze_v2/payments/"]
  r6_prefixes    = ["silver/runtime/trade/catalog/completed/", "silver/runtime/trade/catalog-data/runs/"]
  glue_base      = "arn:aws:glue:ap-northeast-1:${data.aws_caller_identity.current.account_id}"
  silver_tables  = ["silver_runs", "order_amount_checks"]
  gold_tables    = ["gold_runs", "order_sales_hourly_runs", "product_sales_daily_runs", "refresh_holds_runs"]
  funnel_enabled = var.enabled && var.enable_funnel_access
  funnel_input   = "bronze_v2/clickstream/"
  funnel_outputs = ["silver/runtime/clicks/", "gold_a/runtime/funnels/"]
  funnel_tables  = ["funnel_daily_runs", "funnel_session_product_runs"]
}

resource "aws_iam_role_policy" "funnel_s3" {
  for_each = local.funnel_enabled ? aws_iam_role.this : {}
  name     = "funnel-input-output-and-multipart"
  role     = each.value.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Sid = "ClickstreamRead", Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${var.bucket_arn}/${local.funnel_input}*"] },
      { Sid = "FunnelOutputAndMultipart", Effect = "Allow", Action = local.object_actions, Resource = [for p in local.funnel_outputs : "${var.bucket_arn}/${p}*"] },
      { Sid = "DirectoryProbes", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in concat([local.funnel_input], local.funnel_outputs) : "${var.bucket_arn}/${trimsuffix(p, "/")}"] },
      { Sid = "FunnelScopedListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = flatten([for p in concat([local.funnel_input], local.funnel_outputs) : ["${p}*", trimsuffix(p, "/")]]) } } },
      { Sid = "FunnelMagicWorkingObjectsOnly", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = [for p in local.funnel_outputs : "${var.bucket_arn}/${p}runs/*/*/__magic_job-*/*"] }
      ], length(var.funnel_rollback_run_ids) > 0 ? [
      { Sid = "ApprovedFunnelParquetRollback", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = flatten([for p in concat(["silver/runtime/trade/"], local.funnel_outputs) : [for run_id in sort(tolist(var.funnel_rollback_run_ids)) : "${var.bucket_arn}/${p}runs/${run_id}/*/part-*.parquet"]]) }
    ] : [])
  })
}

resource "aws_iam_role_policy" "funnel_glue" {
  count = local.funnel_enabled ? 1 : 0
  name  = "funnel-existing-tables-publication"
  role  = aws_iam_role.this["driver"].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "FunnelTableReadAndPartitionRegistration", Effect = "Allow"
      Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition", "glue:CreatePartition"]
      Resource = concat(["${local.glue_base}:catalog", "${local.glue_base}:database/gold_a"], [for t in local.funnel_tables : "${local.glue_base}:table/gold_a/${t}"])
    }]
  })
}

resource "aws_iam_role_policy" "bronze_v2" {
  for_each = local.publish_trade ? aws_iam_role.this : {}
  name     = "trade-bronze-v2-read"
  role     = each.value.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in local.bronze_v2 : "${var.bucket_arn}/${p}*"] },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in local.bronze_v2 : "${p}*"] } } }
    ]
  })
}

resource "aws_iam_role_policy" "publication" {
  count = local.publish_trade ? 1 : 0
  name  = "trade-publication-and-reprocess"
  role  = aws_iam_role.this["driver"].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "ReadPublicationTables", Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition"]
        Resource = concat(["${local.glue_base}:catalog", "${local.glue_base}:database/silver", "${local.glue_base}:database/gold_a"],
        [for t in local.silver_tables : "${local.glue_base}:table/silver/${t}"], [for t in local.gold_tables : "${local.glue_base}:table/gold_a/${t}"])
      },
      {
        Sid = "RegisterRunPartitions", Effect = "Allow", Action = ["glue:CreatePartition"]
        Resource = concat(["${local.glue_base}:catalog", "${local.glue_base}:database/silver", "${local.glue_base}:database/gold_a", "${local.glue_base}:table/silver/order_amount_checks"],
        [for t in local.gold_tables : "${local.glue_base}:table/gold_a/${t}"])
      },
      {
        Sid      = "AppendReprocessRequestsAndEvents", Effect = "Allow", Action = ["s3:PutObject"]
        Resource = ["${var.bucket_arn}/pipelines/requests/reprocess/*", "${var.bucket_arn}/pipelines/input-manifests/reprocess/*", "${var.bucket_arn}/gold_b/reprocess_events/silver-*"]
      },
      { Sid = "OwnSilverEventRead", Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${var.bucket_arn}/gold_b/reprocess_events/silver-*"] },
      { Sid = "OwnSilverEventExistence", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = ["gold_b/reprocess_events/silver-*"] } } }
    ]
  })
}

resource "aws_iam_role_policy" "r6_reader" {
  count = local.publish_trade ? 1 : 0
  name  = "silver-r6-published-checks-read"
  role  = var.detection_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition"], Resource = concat(["${local.glue_base}:catalog", "${local.glue_base}:database/silver"], [for t in local.silver_tables : "${local.glue_base}:table/silver/${t}"]) },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in local.r6_prefixes : "${var.bucket_arn}/${p}*"] },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in local.r6_prefixes : "${p}*"] } } }
    ]
  })
}
resource "aws_iam_role" "this" {
  for_each = local.actors
  name     = "clothes-query-dev-${var.service_account_prefix}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"]
      Condition = { StringEquals = {
        "aws:RequestTag/eks-cluster-arn"            = "arn:aws:eks:ap-northeast-1:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
        "aws:RequestTag/kubernetes-namespace"       = var.namespace
        "aws:RequestTag/kubernetes-service-account" = "${var.service_account_prefix}-${each.key}"
      } }
    }]
  })
  lifecycle {
    precondition {
      condition     = alltrue([for action in local.required_actions : contains(var.s3_endpoint_actions, action)])
      error_message = "Update the network endpoint transport permissions before enabling these Spark roles."
    }
  }
}
resource "aws_iam_role_policy" "s3" {
  for_each = local.actors
  name     = "trade-magic-committer"
  role     = aws_iam_role.this[each.key].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Sid = "InputRead", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in sort(tolist(var.read_prefixes)) : "${var.bucket_arn}/${p}*"] },
      { Sid = "OutputAndMultipart", Effect = "Allow", Action = local.object_actions, Resource = [for p in sort(tolist(var.output_prefixes)) : "${var.bucket_arn}/${p}*"] },
      { Sid = "MagicWorkingObjectsOnly", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = [for p in local.magic_patterns : "${var.bucket_arn}/${p}"] },
      { Sid = "SelectedPrefixListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in sort(tolist(setunion(var.read_prefixes, var.output_prefixes))) : "${p}*"] } } },
      { Sid = "BucketLocation", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = [var.bucket_arn] }
      ], var.allow_bucket_multipart_listing ? [
      { Sid = "OptionalMultipartMetadataListing", Effect = "Allow", Action = ["s3:ListBucketMultipartUploads"], Resource = [var.bucket_arn] }
      ] : [], length(var.rollback_run_ids) > 0 ? [
      { Sid = "ApprovedRunParquetRollback", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = [for p in local.rollback_patterns : "${var.bucket_arn}/${p}"] }
      ] : [], [for statement in [
        { Sid = "ProductReferenceObjectsReadOnly", Effect = "Allow", Action = ["s3:GetObject"], Resource = sort(tolist(var.reference_object_arns)) },
        { Sid = "ProductReferenceMetadata", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = ["arn:aws:s3:::hm-ecommerce-data"] },
        { Sid = "ProductReferenceListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = ["arn:aws:s3:::hm-ecommerce-data"], Condition = { StringLike = { "s3:prefix" = flatten([for p in local.reference_keys : [p, "${p}/*"]]) } } }
    ] : statement if length(var.reference_object_arns) > 0])
  })
}
resource "aws_eks_pod_identity_association" "this" {
  for_each        = local.actors
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = "${var.service_account_prefix}-${each.key}"
  role_arn        = aws_iam_role.this[each.key].arn
  depends_on      = [aws_iam_role_policy.s3]
}

locals {
  review_enabled = var.enabled && var.enable_review_access
  review_outputs = ["silver/runtime/reviews/", "gold_a/runtime/reviews/"]
  # V2 is the compatible superset; retain legacy reads during migration only.
  review_inputs  = ["bronze_v2/reviews/", "bronze/reviews/"]
  review_scores  = "pipelines/input-manifests/review-scores/"
  review_results = "athena-results/review-score/"
  review_iceberg = "silver/review_aspect_scores_iceberg/"
  review_db      = "clothes_query_dev_review_score"
}

# Managed policies avoid the existing Driver's aggregate inline-policy size limit.
resource "aws_iam_policy" "review_s3" {
  count = local.review_enabled ? 1 : 0
  name  = "clothes-query-dev-${var.service_account_prefix}-review-data"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Sid = "ReviewInputRead", Effect = "Allow", Action = ["s3:GetObject"], Resource = concat(flatten([for p in local.review_inputs : ["${var.bucket_arn}/${p}*", "${var.bucket_arn}/${trimsuffix(p, "/")}"]]), ["${var.bucket_arn}/${local.review_scores}*"]) },
      { Sid = "ReviewOutputs", Effect = "Allow", Action = local.object_actions, Resource = [for p in local.review_outputs : "${var.bucket_arn}/${p}*"] },
      { Sid = "ReviewOutputDirectoryProbes", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in local.review_outputs : "${var.bucket_arn}/${trimsuffix(p, "/")}"] },
      { Sid = "ReviewListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = flatten([for p in concat(local.review_inputs, [local.review_scores], local.review_outputs) : ["${p}*", trimsuffix(p, "/")]]) } } },
      { Sid = "ReviewMagicCleanup", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = [for p in local.review_outputs : "${var.bucket_arn}/${p}runs/*/*/__magic_job-*/*"] }
      ], length(var.review_rollback_run_ids) > 0 ? [
      { Sid = "ApprovedReviewParquetRollback", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = flatten([for p in local.review_outputs : [for id in sort(tolist(var.review_rollback_run_ids)) : "${var.bucket_arn}/${p}runs/${id}/*/part-*.parquet"]]) }
    ] : [])
  })
}

resource "aws_iam_role_policy_attachment" "review_s3" {
  for_each   = local.review_enabled ? aws_iam_role.this : {}
  role       = each.value.name
  policy_arn = aws_iam_policy.review_s3[0].arn
}

resource "aws_iam_policy" "review_driver" {
  count = local.review_enabled ? 1 : 0
  name  = "clothes-query-dev-${var.service_account_prefix}-review-query"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "ExistingReviewWorkgroup", Effect = "Allow", Action = ["athena:GetWorkGroup", "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution"], Resource = ["arn:aws:athena:ap-northeast-1:${data.aws_caller_identity.current.account_id}:workgroup/clothes-query-dev-athena-review-score"] },
      { Sid = "ReviewSourceMetadata", Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition"], Resource = ["${local.glue_base}:catalog", "${local.glue_base}:database/${local.review_db}", "${local.glue_base}:table/${local.review_db}/review_aspect_scores_latest", "${local.glue_base}:table/${local.review_db}/review_aspect_scores"] },
      { Sid = "ReadOnlyScoreIceberg", Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${var.bucket_arn}/${local.review_iceberg}*"] },
      { Sid = "ReviewResultsAndFrozenInput", Effect = "Allow", Action = local.object_actions, Resource = ["${var.bucket_arn}/${local.review_results}*", "${var.bucket_arn}/${local.review_scores}*"] },
      { Sid = "ReviewQueryListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in [local.review_iceberg, local.review_results, local.review_scores] : "${p}*"] } } },
      { Sid = "PublishExistingReviewGoldTables", Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition", "glue:CreatePartition"], Resource = ["${local.glue_base}:catalog", "${local.glue_base}:database/gold_a", "${local.glue_base}:table/gold_a/review_product_daily_runs", "${local.glue_base}:table/gold_a/review_aspect_daily_runs"] }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "review_driver" {
  count      = local.review_enabled ? 1 : 0
  role       = aws_iam_role.this["driver"].name
  policy_arn = aws_iam_policy.review_driver[0].arn
}
