# 거래·회원 시뮬레이터(simulator/) ECS Fargate 실행 기반 (2026-10-21, infra/ecs-simulator)
#
# 만드는 것
#   - ECR 저장소 1개 (이미지는 sim/ecs-image 의 README 순서로 사용자가 빌드·push)
#   - ECS 클러스터, 태스크용 보안 그룹, IAM 역할 2개(태스크 실행 / 태스크), 로그 그룹
#   - 데이터 오염용 DB 접속 문자열을 담을 Secrets Manager secret (값은 사용자가 넣는다. Terraform 에 값을 두지 않는다)
#   - image_digest 를 줬을 때만: 태스크 정의(같은 이미지 컨테이너 3개 + 공유 볼륨) + 서비스(태스크 1개, ECS Exec 켬)
#
# 컨테이너 3개는 같은 태스크 안에서 공유 볼륨(/control)의 제어 파일로 소통한다.
# 컨트롤러가 control.json 을 쓰고, member·behavior 가 1초마다 읽는다(태스크를 나누면 이 파일을 공유할 수 없다).
#
# 만들지 않는 것
#   - RDS 접근 허용: rds 스택의 database_clients(비공개 입력)에 이 스택의 security_group_id 를 넣는다
#   - API 내부 ALB 허용 대역: api chart 의 runtime.local.yaml(inboundCIDRs) 에서 정한다

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# 내부 ALB(HTTP 80)와 RDS(5432) 로 나가는 규칙을 VPC 대역으로만 연다
data "aws_vpc" "this" {
  id = var.vpc_id
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  deploy     = var.image_digest != ""

  app_log_group = "/ecs/${var.name}"
  control_dir   = "/control"
  # 컨트롤러 정답표(incident_log). simulator/README.md "정답표" 절의 키 접두어
  incident_arn = "${var.bucket_arn}/ground_truth/incident_log/*"

  # 세 컨테이너 공통. 시뮬레이터는 API 로만 쓰고 읽는다(DB 계정·Kafka 인증서 없음)
  common_environment = [
    { name = "SIM_BACKEND", value = "api" },
    { name = "SIM_API_URL", value = var.api_url },
    { name = "SIM_CLICK_SINK", value = "api" },
    { name = "SIM_LIVE_SPEED", value = "1" },
    { name = "SIM_CONTROL_FILE", value = "${local.control_dir}/control.json" },
    { name = "AWS_REGION", value = var.region },
  ]
}

# ------------------------------------------------------------------ ECR
resource "aws_ecr_repository" "this" {
  name = "clothes-query-dev/simulator"
  # 같은 태그를 덮어쓰지 못하게 한다. 태스크 정의에는 digest 로 넣는다
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

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
  # Container Insights 는 추가 요금이 있어 끈다
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# ------------------------------------------------------------------ 보안 그룹
# 들어오는 연결은 없다(컨트롤러 화면은 ECS Exec 포트 포워딩으로 본다).
resource "aws_security_group" "task" {
  name        = "${var.name}-task"
  description = "simulator Fargate task (egress only)"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.task.id
  description       = "HTTPS to AWS APIs (ECR, Logs, Secrets Manager, SSM)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "api_alb" {
  security_group_id = aws_security_group.task.id
  description       = "HTTP to the internal API ALB"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = data.aws_vpc.this.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "postgres" {
  security_group_id = aws_security_group.task.id
  description       = "PostgreSQL to RDS (controller data pollution only)"
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
  cidr_ipv4         = data.aws_vpc.this.cidr_block
}

# ------------------------------------------------------------------ Secret (데이터 오염용 DB 접속 문자열)
# 값(postgresql://clothes_sim_admin:…@<RDS>:5432/postgres?sslmode=verify-full&sslrootcert=…)은 사용자가 put-secret-value 로 넣는다.
# 컨트롤러 컨테이너에만 환경변수 DATABASE_URL 로 주입한다.
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.name}/sim-admin-database-url"
  description             = "DATABASE_URL for the simulator controller data pollution account (value set by the operator)"
  recovery_window_in_days = 7
}

# ------------------------------------------------------------------ 로그
resource "aws_cloudwatch_log_group" "app" {
  name              = local.app_log_group
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

# 태스크 시작 때 DB 접속 문자열 secret 하나만 읽는다
data "aws_iam_policy_document" "execution_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database_url.arn]
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  name   = "sim-admin-database-url"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secret.json
}

# ------------------------------------------------------------------ IAM: 태스크 역할 (시뮬레이터 코드가 씀)
# - 컨트롤러 정답표를 ground_truth/incident_log/ 에 쓰기 (--incident-log s3)
# - ECS Exec(포트 포워딩으로 컨트롤러 화면 보기)용 SSM 메시지 채널
data "aws_iam_policy_document" "task" {
  statement {
    sid       = "WriteIncidentLog"
    actions   = ["s3:PutObject"]
    resources = [local.incident_arn]
  }
  statement {
    sid = "EcsExec"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "task" {
  name   = "incident-log-and-exec"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ------------------------------------------------------------------ 태스크 정의 (image_digest 가 있을 때만)
# 같은 이미지(ENTRYPOINT sim), 명령만 다르다. 셋 다 essential 이라 하나가 죽으면 태스크째 다시 뜬다.
resource "aws_ecs_task_definition" "this" {
  count                    = local.deploy ? 1 : 0
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  # 태스크 안의 컨테이너끼리만 공유하는 임시 볼륨 (제어 파일)
  volume {
    name = "control"
  }

  lifecycle {
    precondition {
      condition     = var.api_url != ""
      error_message = "api_url (internal ALB URL) is required when image_digest is set."
    }
  }

  container_definitions = jsonencode([
    for c in [
      {
        name    = "controller"
        command = ["controller", "serve", "--incident-log", "s3"]
        environment = concat(local.common_environment, [
          { name = "S3_BUCKET", value = var.bucket_name },
          { name = "SIM_ALLOW_REMOTE_DB", value = "1" },
        ])
        secrets   = [{ name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn }]
        dependsOn = []
      },
      {
        name        = "member"
        command     = ["member", "live"]
        environment = local.common_environment
        secrets     = []
        dependsOn   = [{ containerName = "controller", condition = "START" }]
      },
      {
        name        = "behavior"
        command     = ["behavior", "live"]
        environment = local.common_environment
        secrets     = []
        dependsOn   = [{ containerName = "controller", condition = "START" }]
      },
      ] : {
      name        = c.name
      image       = "${aws_ecr_repository.this.repository_url}@${var.image_digest}"
      essential   = true
      command     = c.command
      environment = c.environment
      secrets     = c.secrets
      dependsOn   = c.dependsOn
      mountPoints = [{ sourceVolume = "control", containerPath = local.control_dir, readOnly = false }]
      # ECS Exec 가 권장하는 init 프로세스. SIGTERM 이 sim 프로세스까지 전달된다(요약 출력 뒤 종료)
      linuxParameters = { initProcessEnabled = true }
      stopTimeout     = 30
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "sim"
        }
      }
    }
  ])
}

# ------------------------------------------------------------------ 서비스 (태스크 1개, 온디맨드)
resource "aws_ecs_service" "this" {
  count                  = local.deploy ? 1 : 0
  name                   = var.name
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.this[0].arn
  desired_count          = var.desired_count
  launch_type            = "FARGATE"
  platform_version       = "LATEST"
  enable_execute_command = true
  propagate_tags         = "TASK_DEFINITION"

  # 시뮬레이터가 둘 겹쳐 돌면 트래픽이 두 배가 되고 정답표가 어긋난다. 교체할 때 옛 태스크를 먼저 내린다
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }
}
