# 리뷰 시뮬레이터(review-simulator) ECS Fargate 실행 기반 (2026-10-18, sim/review-ecs)
#
# 만드는 것
#   - ECR 저장소 1개 (이미지는 review-simulator/deploy/deploy.py 가 빌드해서 올린다)
#   - ECS 클러스터, 태스크용 보안 그룹, IAM 역할 3개(태스크 실행 / 태스크 / 스케줄러)
#   - Bedrock API 키를 담을 Secrets Manager secret (값은 deploy/secret.py 가 넣는다. Terraform 에 값을 두지 않는다)
#   - RDS 접속 주소(ORDERS_DATABASE_URL)를 담을 secret + RDS(5432)로 나가는 보안 그룹 규칙 (2026-10-21, --source rds)
#   - 하루 1번 실행 스케줄 (EventBridge Scheduler). 2026-10-18 lemin: 계속 실행은 보류 → 꺼진(DISABLED) 상태로 만든다
#   - 관제: 앱 로그, 태스크 종료 기록 로그, 오류 지표, CloudWatch 대시보드, (선택) 이메일 알림·예산 알림
#   - 스크립트가 읽을 설정 묶음 (SSM Parameter Store, JSON 한 개)
#
# 만들지 않는 것
#   - 태스크 정의: 이미지 태그·실행 옵션(REVIEW_RATE 등)이 자주 바뀌어서 deploy/switch 스크립트가 새 리비전을 등록한다.
#     Terraform 이 태스크 정의를 들고 있으면 스크립트가 바꾼 값을 다음 apply 가 되돌린다.
#   - RDS 쪽 허용(들어오는 규칙): RDS 스택 담당이 infra/stacks/rds 의 database_clients 에 이 모듈의
#     security_group_id 출력을 넣고 apply 한다. 이 모듈은 나가는 쪽(5432)만 연다.
#   - RDS 읽기 전용 DB 계정: DB 안에서 SQL 로 만든다(review-simulator/deploy/README.md "RDS 주문 읽기").

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # 스크립트(deploy.py)가 이 이름으로 태스크 정의를 등록한다. 스케줄은 이 패밀리의 리비전을 실행한다
  task_family    = var.name
  container_name = "review-simulator"
  # 리비전 번호 없이 패밀리까지만 쓴 ARN. 스케줄을 켤 때(onoff.py on) 최신 리비전 ARN 으로 바꿔 넣는다
  task_family_arn = "arn:${local.partition}:ecs:${var.region}:${local.account_id}:task-definition/${local.task_family}"

  # S3 경로 (버킷 이름은 공개 저장소에 쓰지 않고 network·storage 스택 state 에서 받는다)
  lake_root     = "s3://${var.bucket_name}/${var.lake_prefix}"
  input_root    = "s3://${var.bucket_name}/${var.input_prefix}"
  reviews_arn   = "${var.bucket_arn}/${var.lake_prefix}/reviews/*"
  input_arn     = "${var.bucket_arn}/${var.input_prefix}/*"
  app_log_group = "/ecs/${var.name}"
  # EventBridge 가 로그를 쓰는 로그 그룹은 /aws/events/ 로 시작하게 둔다(콘솔 규칙과 같게)
  events_log_group = "/aws/events/${var.name}"
  metric_namespace = "ClothesQuery/ReviewSimulator"
  alarm_enabled    = var.alarm_email != ""
  budget_enabled   = var.budget_email != ""
}

# ------------------------------------------------------------------ ECR
resource "aws_ecr_repository" "this" {
  name = "clothes-query-dev/ecs-review-simulator"
  # 같은 태그를 덮어쓰지 못하게 한다. 태그 = <버전>-<커밋> (deploy.py)
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

# 이미지는 최근 var.keep_images 개만 남긴다 (이미지 한 개 약 0.3GB, 저장 요금 절약)
resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last ${var.keep_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_images
      }
      action = { type = "expire" }
    }]
  })
}

# ------------------------------------------------------------------ ECS 클러스터
resource "aws_ecs_cluster" "this" {
  name = var.name
  # Container Insights 는 추가 요금이 있어 끈다. 관제는 아래 로그·대시보드로 한다
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# ------------------------------------------------------------------ 보안 그룹
# 들어오는 연결은 없다. 나가는 연결은 HTTPS(Bedrock·ECR·Secrets Manager·CloudWatch Logs, S3 는 Gateway Endpoint)만 연다.
# RDS(PostgreSQL 5432)로 나가는 연결도 연다(2026-10-21, --source rds). 대상은 VPC 안쪽 주소로만 제한한다.
# RDS 쪽에서는 RDS 담당이 이 보안 그룹 ID 를 database_clients 에 넣어야 실제로 연결된다.
resource "aws_security_group" "task" {
  name        = "${var.name}-task"
  description = "review-simulator Fargate task (egress HTTPS only)"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.task.id
  description       = "HTTPS to AWS APIs and Bedrock"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------------ Secret (Bedrock API 키)
# 값은 넣지 않는다. deploy/secret.py 가 PutSecretValue 로 넣고, 태스크 정의가 환경변수 AWS_BEARER_TOKEN_BEDROCK 로 주입한다.
# RDS 가 있는 VPC 의 주소 범위. 5432 나가는 규칙을 VPC 안으로만 열 때 쓴다
data "aws_vpc" "this" {
  id = var.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "postgres" {
  security_group_id = aws_security_group.task.id
  description       = "PostgreSQL to RDS in the same VPC (orders read, --source rds)"
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
  cidr_ipv4         = data.aws_vpc.this.cidr_block
}

resource "aws_secretsmanager_secret" "bedrock_api_key" {
  name                    = "${var.name}/bedrock-api-key"
  description             = "Bedrock API key for review-simulator (value set by deploy/secret.py)"
  recovery_window_in_days = 7
}

# ------------------------------------------------------------------ 로그
resource "aws_cloudwatch_log_group" "app" {
  name              = local.app_log_group
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "events" {
  name              = local.events_log_group
  retention_in_days = var.log_retention_days
}

# ------------------------------------------------------------------ IAM: 태스크 실행 역할 (ECS 에이전트가 씀)
data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# ECR 이미지 받기 + CloudWatch Logs 쓰기 (AWS 관리형 정책)
resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# 태스크 시작 때 secret 두 개(Bedrock API 키, RDS 접속 주소)만 읽는다
# ------------------------------------------------------------------ Secret (RDS 접속 주소)
# 값(postgresql://읽기전용계정:비밀번호@RDS주소:5432/DB)은 넣지 않는다. deploy/secret.py --orders-db 가 넣는다.
# 태스크 정의는 ORDERS_SOURCE=rds 일 때만 이 secret 을 ORDERS_DATABASE_URL 로 주입한다(값이 비어 있으면 태스크가 시작을 못 하므로).
resource "aws_secretsmanager_secret" "orders_database_url" {
  name                    = "${var.name}/orders-database-url"
  description             = "RDS read-only connection URL for review-simulator --source rds (value set by deploy/secret.py --orders-db)"
  recovery_window_in_days = 7
}

data "aws_iam_policy_document" "execution_secret" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.bedrock_api_key.arn,
      aws_secretsmanager_secret.orders_database_url.arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  name   = "bedrock-api-key"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secret.json
}

# ------------------------------------------------------------------ IAM: 태스크 역할 (시뮬레이터 코드가 씀)
# - bronze/reviews/ 에 리뷰 파티션 쓰기 (rsim run --sink lake, rsim inject)
# - sim-input/review-simulator/ 에서 입력 읽기 (incidents JSON, 직접 쓴 리뷰 CSV/JSONL)
# 정답 라벨(reviews_truth) S3 저장은 2026-10-18 lemin 결정으로 차후 개선이라 권한을 주지 않는다(컨테이너 안에만 쓰고 버려짐).
# Bedrock 은 API 키로 호출하므로 IAM 권한이 필요 없다.
data "aws_iam_policy_document" "task" {
  statement {
    sid       = "WriteReviews"
    actions   = ["s3:PutObject"]
    resources = [local.reviews_arn]
  }
  statement {
    sid       = "ReadInputs"
    actions   = ["s3:GetObject"]
    resources = [local.input_arn]
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "task" {
  name   = "lake-access"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ------------------------------------------------------------------ IAM: 스케줄러 역할 (하루 1번 RunTask)
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "RunTask"
    actions   = ["ecs:RunTask"]
    resources = ["${local.task_family_arn}:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }
  statement {
    sid       = "TagTask"
    actions   = ["ecs:TagResource"]
    resources = ["arn:${local.partition}:ecs:${var.region}:${local.account_id}:task/${aws_ecs_cluster.this.name}/*"]
  }
  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.task.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "run-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

# ------------------------------------------------------------------ 하루 1번 실행 스케줄
# 2026-10-18 lemin: 계속 실행(스케줄)은 보류. 그래서 DISABLED 로 만들고, 켜고 끄는 것은 deploy/onoff.py 가 한다.
# onoff.py on 은 실행할 태스크 정의를 최신 리비전으로 바꾸고 ENABLED 로 바꾼다.
# 스크립트가 바꾸는 두 값(state, 태스크 정의 ARN)은 Terraform 이 되돌리지 않게 ignore_changes 로 둔다.
resource "aws_scheduler_schedule" "daily" {
  name                         = "${var.name}-daily"
  description                  = "review-simulator: yesterday(UTC) reviews to S3 bronze"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = "DISABLED"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn

    # 실패해도 다시 실행하지 않는다 (Bedrock 비용이 두 번 들지 않게). 실패는 대시보드·알림으로 본다
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 3600
    }

    ecs_parameters {
      task_definition_arn = local.task_family_arn
      launch_type         = "FARGATE"
      task_count          = 1
      propagate_tags      = "TASK_DEFINITION"
      network_configuration {
        subnets          = var.subnet_ids
        security_groups  = [aws_security_group.task.id]
        assign_public_ip = false
      }
    }
  }

  lifecycle {
    ignore_changes = [state, target[0].ecs_parameters[0].task_definition_arn]
  }
}

# ------------------------------------------------------------------ 관제: 태스크 종료 기록
# ECS 는 끝난 태스크 정보를 1시간쯤만 보여 준다. 종료 이벤트를 로그로 남겨 대시보드·status.py 에서 본다.
resource "aws_cloudwatch_event_rule" "task_stopped" {
  name        = "${var.name}-task-stopped"
  description = "review-simulator task stopped events"
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.this.arn]
      lastStatus = ["STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "task_stopped" {
  rule = aws_cloudwatch_event_rule.task_stopped.name
  arn  = aws_cloudwatch_log_group.events.arn
}

data "aws_iam_policy_document" "events_to_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.events.arn}:*"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.task_stopped.arn]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "events_to_logs" {
  policy_name     = "${var.name}-events"
  policy_document = data.aws_iam_policy_document.events_to_logs.json
}

# ------------------------------------------------------------------ 관제: 지표
# 실패한 실행: 컨테이너가 0 이 아닌 코드로 끝났거나, 시작 단계에서 멈춤(이미지·secret 문제 등)
resource "aws_cloudwatch_log_metric_filter" "failed_runs" {
  name           = "${var.name}-failed-runs"
  log_group_name = aws_cloudwatch_log_group.events.name
  pattern        = "{ ($.detail.stopCode != \"EssentialContainerExited\") || ($.detail.containers[0].exitCode != 0) }"
  metric_transformation {
    name          = "FailedRuns"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

# 앱 로그의 ERROR 줄 수 (Bedrock 오류, 응답 파싱 실패 등)
resource "aws_cloudwatch_log_metric_filter" "errors" {
  name           = "${var.name}-errors"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "\" ERROR \""
  metric_transformation {
    name          = "Errors"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

# ------------------------------------------------------------------ 관제: (선택) 이메일 알림
resource "aws_sns_topic" "alerts" {
  count = local.alarm_enabled ? 1 : 0
  name  = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = local.alarm_enabled ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "failed_runs" {
  count               = local.alarm_enabled ? 1 : 0
  alarm_name          = "${var.name}-failed-runs"
  alarm_description   = "review-simulator task failed (see dashboard)"
  namespace           = local.metric_namespace
  metric_name         = "FailedRuns"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}

# ------------------------------------------------------------------ 관제: (선택) 월 예산 알림
# 태그 Component=ecs-review-simulator 가 붙은 비용(Fargate, ECR, 로그, Secret)만 본다.
# 비용 할당 태그는 결제 콘솔에서 한 번 활성화해야 집계된다. Bedrock 은 API 키 호출이라 태그가 붙지 않으므로
# 대시보드의 토큰 기반 추정 비용과 deploy/status.py --cost 로 본다.
resource "aws_budgets_budget" "monthly" {
  count        = local.budget_enabled ? 1 : 0
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Component$ecs-review-simulator"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}

# ------------------------------------------------------------------ 관제: 대시보드
locals {
  # 실행별 요약: run.py 가 마지막에 남기는 "끝: 전송 …" 줄과 "검수 호출 …" 줄을 읽는다.
  # 추정 비용 = 토큰 수 x 단가(var.bedrock_price_*, 100만 토큰당 USD). 로그 문구를 바꾸면 이 쿼리도 같이 바꾼다.
  runs_query = join("\n", [
    "SOURCE '${local.app_log_group}'",
    "| filter @message like /끝: 전송|검수 호출/",
    "| parse @message /끝: 전송 (?<sent>\\d+)건, 건너뜀 (?<skipped>\\d+)건, 모델 호출 \\d+회, 입력 토큰 (?<gin>\\d+), 출력 토큰 (?<gout>\\d+)/",
    "| parse @message /검수 호출 \\d+회, 입력 토큰 (?<vin>\\d+), 출력 토큰 (?<vout>\\d+)/",
    "| stats latest(@timestamp) as finished, sum(sent) as reviews, sum(skipped) as dropped, sum(gin) as gen_in, sum(gout) as gen_out, sum(vin) as ver_in, sum(vout) as ver_out by @logStream",
    "| fields (gen_in + ver_in) * ${var.bedrock_price_input} / 1000000 + (gen_out + ver_out) * ${var.bedrock_price_output} / 1000000 as est_usd",
    "| sort finished desc",
    "| limit 30",
  ])
  stops_query = join("\n", [
    "SOURCE '${local.events_log_group}'",
    "| fields @timestamp, detail.stopCode as stop_code, detail.containers.0.exitCode as exit_code, detail.stoppedReason as reason, detail.taskDefinitionArn as task_def",
    "| sort @timestamp desc",
    "| limit 20",
  ])
  errors_query = join("\n", [
    "SOURCE '${local.app_log_group}'",
    "| filter @message like / (ERROR|WARNING) /",
    "| fields @timestamp, @message",
    "| sort @timestamp desc",
    "| limit 30",
  ])
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = var.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = "## 리뷰 시뮬레이터 (ECS)\n상태 확인: `python deploy/status.py` · 켜기/끄기: `deploy/onoff.py` · 실행 비율: `deploy/switch.py`. 추정 비용은 토큰 수 x 단가(100만 토큰당 입력 USD ${var.bedrock_price_input}, 출력 USD ${var.bedrock_price_output})이고 실제 청구액은 status.py --cost 로 본다."
        }
      },
      {
        type = "log", x = 0, y = 2, width = 24, height = 7
        properties = {
          title  = "실행별 리뷰 수·토큰·추정 Bedrock 비용 (최근 30회)"
          region = var.region
          view   = "table"
          query  = local.runs_query
        }
      },
      {
        type = "metric", x = 0, y = 9, width = 8, height = 6
        properties = {
          title   = "실패한 실행 / ERROR 줄 (일별)"
          region  = var.region
          view    = "timeSeries"
          stat    = "Sum"
          period  = 86400
          metrics = [[local.metric_namespace, "FailedRuns"], [local.metric_namespace, "Errors"]]
        }
      },
      {
        type = "log", x = 8, y = 9, width = 16, height = 6
        properties = {
          title  = "태스크 종료 기록 (종료 코드·이유)"
          region = var.region
          view   = "table"
          query  = local.stops_query
        }
      },
      {
        type = "log", x = 0, y = 15, width = 24, height = 6
        properties = {
          title  = "최근 ERROR / WARNING 로그"
          region = var.region
          view   = "table"
          query  = local.errors_query
        }
      },
    ]
  })
}

# ------------------------------------------------------------------ 스크립트용 설정 묶음
# deploy/*.py 는 Terraform 을 몰라도 되게 이 값 하나만 읽는다. 계정 ID·버킷 이름이 들어 있어 저장소에는 두지 않는다.
resource "aws_ssm_parameter" "config" {
  name        = var.config_parameter_name
  description = "review-simulator deploy script config (managed by Terraform)"
  type        = "String"
  value = jsonencode({
    region               = var.region
    cluster              = aws_ecs_cluster.this.name
    cluster_arn          = aws_ecs_cluster.this.arn
    task_family          = local.task_family
    container_name       = local.container_name
    cpu                  = tostring(var.cpu)
    memory               = tostring(var.memory)
    ecr_repository_url   = aws_ecr_repository.this.repository_url
    execution_role_arn   = aws_iam_role.execution.arn
    task_role_arn        = aws_iam_role.task.arn
    secret_arn           = aws_secretsmanager_secret.bedrock_api_key.arn
    orders_db_secret_arn = aws_secretsmanager_secret.orders_database_url.arn
    subnets              = var.subnet_ids
    security_groups      = [aws_security_group.task.id]
    app_log_group        = aws_cloudwatch_log_group.app.name
    events_log_group     = aws_cloudwatch_log_group.events.name
    schedule_name        = aws_scheduler_schedule.daily.name
    schedule_group       = aws_scheduler_schedule.daily.group_name
    lake_root            = local.lake_root
    input_root           = local.input_root
    dashboard            = aws_cloudwatch_dashboard.this.dashboard_name
  })
}
