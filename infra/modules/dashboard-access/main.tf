data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account    = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  glue       = "arn:${local.partition}:glue:ap-northeast-1:${local.account}"
  bucket     = trimprefix(var.bucket_arn, "arn:${local.partition}:s3:::")
  cluster    = "arn:${local.partition}:eks:ap-northeast-1:${local.account}:cluster/${var.cluster_name}"
  data_paths = ["gold_b/anomaly/", "gold_b/reprocess_events/", "agent/investigation_reports/", var.model_registry_prefix, "bronze_v2/reviews/"]
  pipeline_status_tables = [
    "gold_b/bronze_lag_snapshots", "gold_b/topic_messages", "gold_b/payment_events", "gold_b/malformed_events",
    "silver/silver_runs", "gold_a/gold_runs"
  ]
  pipeline_status_paths = concat([
    "gold_b/bronze_lag_snapshots/", "gold_b/topic_messages/", "gold_b/payment_events/", "gold_b/malformed_events/",
    "silver/runtime/trade/catalog/completed/", "gold_a/catalog/"
  ], [for channel in ["trade", "funnels", "reviews"] : "gold_a/runtime/${channel}/catalog/completed/"])
  # 감성분석 모델 화면이 읽는 곳(읽기 전용). Glue 는 athena-review-score 스택의 DB·표·뷰, S3 는 Iceberg 표 위치와 Silver 리뷰 실행 출력, 실행 요약 JSON.
  review_score_tables = ["review_aspect_scores", "review_score_log", "review_aspect_scores_latest", "silver_reviews_runs"]
  review_score_objects = [
    "silver/review_aspect_scores_iceberg/", "silver/review_score_log_iceberg/",
    "silver/runtime/reviews/current.json", "silver/runtime/reviews/completed/",
    "silver/runtime/reviews/runs/*/silver_reviews/", "staging/review-score/_summary_scores_"
  ]
  review_score_list_prefixes = [
    "silver/review_aspect_scores_iceberg/", "silver/review_score_log_iceberg/",
    "silver/runtime/reviews/", "staging/review-score/"
  ]
  gold_a_datasets = {
    trade   = ["order_sales_hourly", "product_sales_daily", "refresh_holds"]
    funnels = ["funnel_daily", "funnel_session_product", "refresh_holds"]
    reviews = ["review_product_daily", "review_aspect_daily"]
  }
  gold_a_tables = concat(["gold_runs"], distinct(flatten([
    for datasets in values(local.gold_a_datasets) : [for dataset in datasets : "${dataset}_runs"]
  ])))
  gold_a_paths = concat(
    [for channel in keys(local.gold_a_datasets) : "gold_a/runtime/${channel}/catalog/completed/"],
    flatten([for channel, datasets in local.gold_a_datasets : [for dataset in datasets : "gold_a/runtime/${channel}/runs/*/${dataset}/"]])
  )
}

resource "aws_iam_role_policy" "gold_a_read" {
  count = var.enable_gold_a_reads ? 1 : 0
  name  = "gold-a-metrics-read-only"
  role  = aws_iam_role.dashboard.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "GoldAMetricsMetadata"
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions", "glue:GetPartition", "glue:BatchGetPartition"]
        Resource = concat(["${local.glue}:catalog", "${local.glue}:database/gold_a"], [for table in local.gold_a_tables : "${local.glue}:table/gold_a/${table}"])
      },
      { Sid = "GoldAMetricsObjects", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for path in local.gold_a_paths : "${var.bucket_arn}/${path}*"] },
      {
        Sid       = "GoldAMetricsListing"
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = [var.bucket_arn]
        Condition = { StringLike = { "s3:prefix" = flatten([for path in local.gold_a_paths : [trimsuffix(path, "/"), "${path}*"]]) } }
      }
    ]
  })
}

resource "aws_iam_role_policy" "pipeline_status" {
  count = var.enable_pipeline_status_reads ? 1 : 0
  name  = "pipeline-status-read-only"
  role  = aws_iam_role.dashboard.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PipelineStatusMetadata", Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions", "glue:GetPartition", "glue:BatchGetPartition"]
        Resource = concat(["${local.glue}:catalog"], [for db in ["gold_b", "silver", "gold_a"] : "${local.glue}:database/${db}"],
        [for table in local.pipeline_status_tables : "${local.glue}:table/${table}"])
      },
      { Sid = "PipelineStatusObjects", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in local.pipeline_status_paths : "${var.bucket_arn}/${p}*"] },
      { Sid = "PipelineStatusListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in local.pipeline_status_paths : "${p}*"] } } }
    ]
  })
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
      },
      # AWS에만 있던 문을 코드로 옮김(2026-10-25). 원래 추가한 사람 확인 필요.
      # 결제 관제 화면이 읽는 뷰 gold_b.payment_states, gold_b.payment_attempts 의 메타데이터 조회(glue:GetTable)만 허용한다(TODO F3).
      # 이 문이 코드에 없으면 apply 때 삭제되어 결제 관제가 실데이터를 못 읽는다. 문 순서(맨 뒤)는 AWS의 현재 정책과 맞춘 것이다.
      {
        Sid    = "PaymentViewMetadata"
        Effect = "Allow"
        Action = ["glue:GetTable"]
        Resource = concat(["${local.glue}:catalog", "${local.glue}:database/gold_b"],
        [for t in ["payment_states", "payment_attempts"] : "${local.glue}:table/gold_b/${t}"])
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

# 감성분석 모델 화면용 읽기 전용 정책. Glue 메타데이터 조회 + 점수 Iceberg 표·Silver 리뷰 실행 출력·실행 요약 JSON 의 S3 읽기만 준다.
# 쓰기·Glue DDL 권한은 없다. Silver 리뷰 실행 출력은 Athena 가 상품·작성일·별점과, 점수 차가 큰 후기 확인용 원문(text, 팀 내부용)을 읽는 데 필요하다.
resource "aws_iam_role_policy" "review_score_read" {
  count = var.enable_review_score_reads ? 1 : 0
  name  = "review-score-read-only"
  role  = aws_iam_role.dashboard.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReviewScoreMetadata"
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions", "glue:GetPartition", "glue:BatchGetPartition"]
        Resource = concat(["${local.glue}:catalog", "${local.glue}:database/${var.review_score_database}"], [for t in local.review_score_tables : "${local.glue}:table/${var.review_score_database}/${t}"])
      },
      { Sid = "ReviewScoreObjects", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in local.review_score_objects : "${var.bucket_arn}/${p}*"] },
      { Sid = "ReviewScoreListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in local.review_score_list_prefixes : "${p}*"] } } }
    ]
  })
}
