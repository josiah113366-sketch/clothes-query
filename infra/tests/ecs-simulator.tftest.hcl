mock_provider "aws" {
  override_data {
    target = data.aws_vpc.this
    values = { cidr_block = "10.70.0.0/16" }
  }
  override_data {
    target = data.aws_partition.current
    values = { partition = "aws" }
  }
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "000000000000" }
  }
  override_data {
    target = data.aws_iam_policy_document.ecs_tasks_assume
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.execution_secret
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.task
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

variables {
  name        = "test-sim"
  region      = "ap-northeast-1"
  vpc_id      = "vpc-test"
  subnet_ids  = ["subnet-a", "subnet-c"]
  bucket_name = "test-lake"
  bucket_arn  = "arn:aws:s3:::test-lake"
}

run "base_only_without_image" {
  command = plan
  module { source = "../modules/ecs-simulator" }
  assert {
    condition     = length(aws_ecs_task_definition.this) == 0 && length(aws_ecs_service.this) == 0 && output.service_name == ""
    error_message = "image_digest 가 없으면 기반(ECR, 클러스터, IAM, SG, Secret, 로그)만 만들어야 한다."
  }
  assert {
    condition = (
      aws_ecr_repository.this.name == "clothes-query-dev/simulator" &&
      aws_ecr_repository.this.image_tag_mutability == "IMMUTABLE" &&
      !aws_ecr_repository.this.force_delete
    )
    error_message = "ECR은 시뮬레이터 저장소이고 태그 덮어쓰기 금지·삭제 보호가 있어야 한다."
  }
  assert {
    condition = (
      aws_vpc_security_group_egress_rule.https.cidr_ipv4 == "0.0.0.0/0" && aws_vpc_security_group_egress_rule.https.from_port == 443 &&
      aws_vpc_security_group_egress_rule.api_alb.cidr_ipv4 == "10.70.0.0/16" && aws_vpc_security_group_egress_rule.api_alb.from_port == 80 &&
      aws_vpc_security_group_egress_rule.postgres.cidr_ipv4 == "10.70.0.0/16" && aws_vpc_security_group_egress_rule.postgres.from_port == 5432
    )
    error_message = "나가는 규칙: AWS API 443, VPC 안으로만 80·5432. 들어오는 규칙은 없다."
  }
}

run "three_containers_share_control_volume" {
  command = plan
  module { source = "../modules/ecs-simulator" }
  variables {
    image_digest = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    api_url      = "http://internal-test.local"
  }
  override_resource {
    target          = aws_ecr_repository.this
    values          = { repository_url = "000000000000.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/simulator" }
    override_during = plan
  }
  override_resource {
    target          = aws_secretsmanager_secret.database_url
    values          = { arn = "mock-secret-arn" }
    override_during = plan
  }
  assert {
    condition = (
      toset([for c in jsondecode(aws_ecs_task_definition.this[0].container_definitions) : c.name]) == toset(["controller", "member", "behavior"]) &&
      alltrue([for c in jsondecode(aws_ecs_task_definition.this[0].container_definitions) :
        c.essential && endswith(c.image, "@sha256:0000000000000000000000000000000000000000000000000000000000000000") &&
        one(c.mountPoints).sourceVolume == "control" && one(c.mountPoints).containerPath == "/control" &&
        contains([for e in c.environment : "${e.name}=${e.value}"], "SIM_BACKEND=api") &&
        contains([for e in c.environment : "${e.name}=${e.value}"], "SIM_LIVE_SPEED=1") &&
        contains([for e in c.environment : "${e.name}=${e.value}"], "SIM_CONTROL_FILE=/control/control.json")
      ]) &&
      one(aws_ecs_task_definition.this[0].volume).name == "control"
    )
    error_message = "이미지 하나, 필수 컨테이너 3개, 공유 볼륨의 같은 제어 파일, API 백엔드, 실제 시각 배속."
  }
  assert {
    condition = alltrue([for c in jsondecode(aws_ecs_task_definition.this[0].container_definitions) :
      c.name == "controller" ? (length(c.secrets) == 1 && c.secrets[0].name == "DATABASE_URL" && c.secrets[0].valueFrom == "mock-secret-arn") : length(c.secrets) == 0
    ])
    error_message = "데이터 오염용 DATABASE_URL 은 컨트롤러만 받아야 한다."
  }
  assert {
    condition = (
      aws_ecs_service.this[0].desired_count == 1 &&
      aws_ecs_service.this[0].launch_type == "FARGATE" &&
      aws_ecs_service.this[0].enable_execute_command &&
      aws_ecs_service.this[0].deployment_minimum_healthy_percent == 0 &&
      aws_ecs_service.this[0].deployment_maximum_percent == 100 &&
      !one(aws_ecs_service.this[0].network_configuration).assign_public_ip
    )
    error_message = "온디맨드 태스크 1개, ECS Exec 켬, 시뮬레이터가 동시에 둘 뜨지 않음, public IP 없음."
  }
}

run "reject_bad_digest" {
  command = plan
  module { source = "../modules/ecs-simulator" }
  variables { image_digest = "latest" }
  expect_failures = [var.image_digest]
}

run "reject_more_than_one_task" {
  command = plan
  module { source = "../modules/ecs-simulator" }
  variables { desired_count = 2 }
  expect_failures = [var.desired_count]
}

run "require_api_url_with_image" {
  command = plan
  module { source = "../modules/ecs-simulator" }
  variables {
    image_digest = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  }
  expect_failures = [aws_ecs_task_definition.this]
}
