# 리뷰 점수화(s2c 합친 모델) SageMaker Processing Job 실행 기반 (stacks/sagemaker-review-score)
#
# 이 모듈이 만드는 것 (모두 "그릇"이다. Processing Job 자체는 만들지 않는다)
#   - Processing Job 이 맡을 IAM 실행 역할 (S3 읽기/쓰기, CloudWatch 로그·지표, DLC 이미지 받기, 선택적 VPC)
#   - (use_vpc=true 일 때) Job 용 보안 그룹: 들어오는 연결 없음, 나가는 HTTPS(443)만
#   - 스크립트(run_processing_job.py)가 읽을 설정 묶음 (SSM Parameter Store, JSON 한 개)
#   - Airflow 가 Job 을 시작할 때 쓰는 IAM 정책(launcher, 어떤 역할에도 자동으로 붙지 않음)
#
# 만들지 않는 것
#   - Processing Job: 호출마다 이름·입력 날짜가 달라서 Terraform 리소스가 될 수 없다. Airflow 의 silver DAG 가 끝난 뒤
#     그 신호를 받아 Airflow 태스크가 SSM 설정을 읽어 만든다(2026-10-21 결정). 그래서 EventBridge 스케줄도 만들지 않는다.
#   - 이메일 알림·월 예산: 2026-10-21 요청으로 뺐다. 실패는 Airflow 태스크 실패와 error/ 경로 파일로 본다.
#   - 버킷·VPC: storage / network 스택 것을 스택이 remote state 로 받아 넘긴다. 이 모듈은 새로 만들지 않는다.
#   - 모델·코드·입력 업로드: deploy/upload_model.py 등 스크립트 몫이다.
#   - Airflow 쪽 권한 연결: launcher 정책을 Airflow 역할에 붙이는 일은 이 스택 밖(workload-access 등)에서 한다.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  vpc_enabled = var.use_vpc

  # S3 리소스 ARN. 버킷 이름은 공개 저장소에 쓰지 않으므로 전부 입력(var.bucket_arn)에서 조립한다.
  review_input_arn = "${var.bucket_arn}/${var.review_input_prefix}/*"
  model_arn        = "${var.bucket_arn}/${var.work_prefix}/model/*"
  # 릴리스 묶음(2026-10-23 결정): <work>/model-registry/releases/<버전>/manifest.json + code/(score_batch.py, requirements.txt).
  # Job 역할은 묶음의 code/ 만 읽고, manifest 는 실행기(launcher)가 읽는다. 예전 <work>/code/ 는 더 쓰지 않는다.
  registry_prefix   = "${var.work_prefix}/model-registry/releases"
  registry_arn      = "${var.bucket_arn}/${local.registry_prefix}/*"
  registry_code_arn = "${var.bucket_arn}/${local.registry_prefix}/*/code/*"
  output_arn        = "${var.bucket_arn}/${var.output_prefix}/*"
  error_arn         = "${var.bucket_arn}/${var.error_prefix}/*"
  # 미점수 후기 입력(select_unscored.py 가 쓰고 Job 이 읽는다)과 후기별 점수 로그(Job 이 쓰는 staging)
  unscored_input_arn = "${var.bucket_arn}/${var.unscored_input_prefix}/*"
  score_log_arn      = "${var.bucket_arn}/${var.score_log_prefix}/*"

  # SageMaker 가 입력 prefix 를 내려받을 때 ListBucket 이 필요하다. 리소스 제한이 안 되어 prefix 조건으로 좁힌다.
  list_prefixes = [
    "${var.review_input_prefix}/*",
    "${var.work_prefix}/model/*",
    "${local.registry_prefix}/*",
    "${var.output_prefix}/*",
    "${var.unscored_input_prefix}/*",
  ]

  # 스크립트가 쓰는 컨테이너 이미지(AWS 공개 DLC). 리전·계정은 변수에서 조립한다.
  image_uri = "${var.dlc_registry_account_id}.dkr.ecr.${var.region}.amazonaws.com/${var.dlc_repository}:${var.dlc_image_tag}"
}

# ------------------------------------------------------------------ IAM: Processing Job 실행 역할
# SageMaker 서비스가 Job 을 돌릴 때 이 역할을 맡는다. SourceAccount 조건으로 다른 계정이 이 역할을 쓰지 못하게 한다.
data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "processing" {
  name               = "${var.name}-processing"
  description        = "SageMaker Processing Job for review scoring (s2c model)"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
}

# S3: 읽기/쓰기를 prefix 단위로 나눈다.
#   - 리뷰 입력(silver/reviews/*)  : 읽기만. Silver 리뷰(KST 작성일 파티션)를 읽는다. Bronze·reviews_truth/·ground_truth/·gold_b/ 는 prefix 가 달라 접근할 수 없다.
#     (같은 scope 폴더 안의 격리 레코드·품질 결과 파일도 이 prefix 아래라 읽을 수 있다. 읽기 전용이다.)
#   - 모델 가중치(<work>/model)와 릴리스 묶음의 실행 코드(<work>/model-registry/releases/<버전>/code): 읽기만.
#   - 점수 결과·오류(output_prefix, error_prefix): 쓰기만. 결과는 <output_prefix>(= staging)/year=/month=/day=/scores_<model_version>_<실행시각>.parquet 로 쌓인다(파일명이 겹치지 않아 덮어쓰기 없음).
data "aws_iam_policy_document" "processing_s3" {
  statement {
    sid     = "ReadReviewsModelCode"
    actions = ["s3:GetObject"]
    resources = [
      local.review_input_arn,
      local.unscored_input_arn,
      local.model_arn,
      local.registry_code_arn,
    ]
  }
  statement {
    sid       = "WriteScores"
    actions   = ["s3:PutObject"]
    resources = [local.output_arn, local.score_log_arn, local.error_arn]
  }
  statement {
    sid       = "ListOnlyUsedPrefixes"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = local.list_prefixes
    }
  }
}

resource "aws_iam_role_policy" "processing_s3" {
  name   = "s3-review-score"
  role   = aws_iam_role.processing.id
  policy = data.aws_iam_policy_document.processing_s3.json
}

# CloudWatch: Job 로그는 계정 공용 로그 그룹 /aws/sagemaker/ProcessingJobs 에 쌓인다(SageMaker 가 자동 생성).
# 이 로그 그룹을 Terraform 으로 만들지는 않는다(다른 Job 과 공용이고 이미 있을 수 있어 import 충돌 위험).
# 지표(CPU·GPU 사용률)는 같은 이름의 네임스페이스로만 쓰도록 조건을 건다.
data "aws_iam_policy_document" "processing_cloudwatch" {
  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:/aws/sagemaker/ProcessingJobs",
      "arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:/aws/sagemaker/ProcessingJobs:*",
    ]
  }
  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # PutMetricData 는 리소스 제한이 안 된다. 네임스페이스 조건으로 좁힌다.
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["/aws/sagemaker/ProcessingJobs"]
    }
  }
}

resource "aws_iam_role_policy" "processing_cloudwatch" {
  name   = "cloudwatch-logs-metrics"
  role   = aws_iam_role.processing.id
  policy = data.aws_iam_policy_document.processing_cloudwatch.json
}

# ECR: AWS 공개 DLC(pytorch-training)만 받는다. 우리 계정 ECR 은 쓰지 않는다.
# GetAuthorizationToken 은 리소스 제한이 안 되는 API 라서 "*" 가 불가피하다.
data "aws_iam_policy_document" "processing_ecr" {
  statement {
    sid       = "EcrToken"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "PullDlcImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = ["arn:${local.partition}:ecr:${var.region}:${var.dlc_registry_account_id}:repository/${var.dlc_repository}"]
  }
}

resource "aws_iam_role_policy" "processing_ecr" {
  name   = "ecr-pull-dlc"
  role   = aws_iam_role.processing.id
  policy = data.aws_iam_policy_document.processing_ecr.json
}

# VPC 에서 실행할 때만: SageMaker 가 Job 용 ENI 를 subnet 에 만들고 지우는 권한.
# 이 EC2 API 들은 리소스 단위 제한을 지원하지 않아 "*" 를 쓴다(AWS 문서가 요구하는 목록 그대로).
data "aws_iam_policy_document" "processing_vpc" {
  statement {
    sid = "JobEni"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:CreateNetworkInterfacePermission",
      "ec2:DeleteNetworkInterface",
      "ec2:DeleteNetworkInterfacePermission",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeVpcs",
      "ec2:DescribeDhcpOptions",
      "ec2:DescribeSubnets",
      "ec2:DescribeSecurityGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "processing_vpc" {
  count  = local.vpc_enabled ? 1 : 0
  name   = "vpc-eni"
  role   = aws_iam_role.processing.id
  policy = data.aws_iam_policy_document.processing_vpc.json
}

# ------------------------------------------------------------------ 보안 그룹 (VPC 실행일 때만)
# 들어오는 연결 없음. 나가는 연결은 HTTPS 만 연다: PyPI(pip install), ECR(이미지), CloudWatch Logs, SageMaker API.
# S3 는 network 스택의 Gateway Endpoint 를 타므로 같은 443 규칙이면 된다. 두 AZ 중 한 곳의 NAT 로 나간다.
resource "aws_security_group" "processing" {
  count       = local.vpc_enabled ? 1 : 0
  name        = "${var.name}-processing"
  description = "SageMaker review-score processing job (egress HTTPS only)"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "https" {
  count             = local.vpc_enabled ? 1 : 0
  security_group_id = aws_security_group.processing[0].id
  description       = "HTTPS to PyPI, ECR, CloudWatch, S3"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------------ Airflow(실행기)용 권한 정책
# 2026-10-21 결정: Job 은 Airflow 의 silver DAG 가 끝난 신호를 받아 Airflow 가 시작한다(스케줄·이메일 알림 없음).
# Airflow 가 쓰는 IAM 역할/Pod Identity 는 이 스택 소관이 아니므로 "붙일 수 있는 정책"만 만들어 ARN 을 내보낸다.
# 붙이는 일(workload-access 스택 또는 Airflow 담당의 역할)은 별도 작업이다. 이 정책은 아무 역할에도 자동으로 붙지 않는다.
data "aws_iam_policy_document" "launcher" {
  statement {
    sid     = "ManageReviewScoreJobs"
    actions = ["sagemaker:CreateProcessingJob", "sagemaker:DescribeProcessingJob", "sagemaker:StopProcessingJob", "sagemaker:AddTags"]
    # Job 이름 접두사로 이 작업만 다룬다.
    resources = ["arn:${local.partition}:sagemaker:${var.region}:${local.account_id}:processing-job/${var.job_name_prefix}-*"]
  }
  statement {
    sid       = "PassProcessingRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.processing.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["sagemaker.amazonaws.com"]
    }
  }
  statement {
    sid       = "ReadScriptConfig"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.config.arn]
  }
  # select_unscored.py(Job 시작 전 단계)를 실행하는 쪽의 S3 권한: Silver 후기 입력 읽기, 미점수 후기 입력 쓰기.
  # 이미 점수가 매겨진 후기를 찾는 Athena 쿼리 권한은 athena-review-score 스택의 runner 정책을 함께 붙여서 받는다.
  statement {
    sid       = "SelectUnscoredReadInput"
    actions   = ["s3:GetObject"]
    resources = [local.review_input_arn]
  }
  statement {
    sid       = "SelectUnscoredWriteInput"
    actions   = ["s3:PutObject"]
    resources = [local.unscored_input_arn]
  }
  # run_processing_job.py 가 Job 을 만들기 전에 릴리스 묶음의 manifest 를 읽고, S3 가중치 목록(이름·크기)을 manifest 와 대조한다.
  statement {
    sid       = "ReadReleaseManifest"
    actions   = ["s3:GetObject"]
    resources = [local.registry_arn]
  }
  statement {
    sid       = "ListWeightsForCheck"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      # 레지스트리 prefix 는 없는 버전을 물었을 때 AccessDenied 대신 NoSuchKey 를 받기 위해 넣는다
      values = ["${var.work_prefix}/model/*", "${local.registry_prefix}/*"]
    }
  }
}

resource "aws_iam_policy" "launcher" {
  name        = "${var.name}-launcher"
  description = "Attach to the Airflow role that starts review-score processing jobs"
  policy      = data.aws_iam_policy_document.launcher.json
}

# ------------------------------------------------------------------ 스크립트용 설정 묶음
# run_processing_job.py 가 Terraform 을 몰라도 되게 이 값 하나만 읽는다(ecs-review-simulator 와 같은 방식).
# 버킷 이름·계정 ID 가 들어 있어 저장소에는 두지 않고 SSM 에만 둔다.
# 스크립트가 읽어서 쓸 것: release(지금 쓸 모델 버전 이름), role_arn, instance_type, volume_size_gb, max_runtime_seconds, job_name_prefix,
#   s3 경로, network(use_vpc=true 일 때만 값이 있음), tags(Job 의 Tags 에 그대로 넣기, 비용 추적용 Component).
# 2026-10-23 결정: 모델 이름·번호·이미지·코드 위치는 릴리스 묶음 manifest 가 정한다. 여기에는 버전과 무관한 값과 release 하나만 둔다.
#   image_uri 는 Job 이 쓰지 않는다. upload_model.py 로 새 묶음을 만들 때 넣는 기본 이미지다(manifest runtime.image_uri 로 복사됨).
resource "aws_ssm_parameter" "config" {
  name        = var.config_parameter_name
  description = "review-score SageMaker processing job script config (managed by Terraform)"
  type        = "String"
  value = jsonencode({
    region              = var.region
    role_arn            = aws_iam_role.processing.arn
    image_uri           = local.image_uri # 새 릴리스 묶음용 기본 이미지. Job 은 manifest 의 이미지를 쓴다
    release             = var.release
    instance_type       = var.instance_type
    volume_size_gb      = var.volume_size_gb
    max_runtime_seconds = var.max_runtime_seconds
    job_name_prefix     = var.job_name_prefix
    bucket              = var.bucket_name
    review_input_root   = "s3://${var.bucket_name}/${var.review_input_prefix}"
    model_prefix        = "s3://${var.bucket_name}/${var.work_prefix}/model/"
    registry_prefix     = "s3://${var.bucket_name}/${local.registry_prefix}/"
    output_prefix       = "s3://${var.bucket_name}/${var.output_prefix}/"
    log_prefix          = "s3://${var.bucket_name}/${var.score_log_prefix}/"
    unscored_prefix     = var.unscored_input_prefix
    error_prefix        = "s3://${var.bucket_name}/${var.error_prefix}/"
    network = local.vpc_enabled ? {
      subnets         = var.subnet_ids
      security_groups = [aws_security_group.processing[0].id]
    } : null
    tags = [
      { Key = "Project", Value = "clothes-query" },
      { Key = "Environment", Value = "dev" },
      { Key = "ManagedBy", Value = "script" },
      { Key = "Component", Value = var.component },
    ]
  })
}
