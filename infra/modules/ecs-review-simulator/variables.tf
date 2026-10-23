variable "name" {
  description = "Resource name prefix (clothes-query-<env>-<purpose>)."
  type        = string
  default     = "clothes-query-dev-ecs-review-simulator"
}

variable "region" {
  type = string
}

variable "vpc_id" {
  description = "Team VPC (network stack output)."
  type        = string
}

variable "subnet_ids" {
  description = "Private app subnets for the Fargate task (network stack app_subnet_ids). Outbound via the shared NAT."
  type        = list(string)
}

variable "bucket_name" {
  description = "Team data lake bucket (storage stack output). Not written to the public repo."
  type        = string
  sensitive   = true
}

variable "bucket_arn" {
  type      = string
  sensitive = true
}

variable "lake_prefix" {
  description = "Bronze prefix; reviews go to <bucket>/<lake_prefix>/reviews/year=/month=/day=/."
  type        = string
  default     = "bronze"
}

variable "input_prefix" {
  description = "Prefix the task may read inputs from (incidents JSON, hand-written review files)."
  type        = string
  default     = "sim-input/review-simulator"
}

variable "cpu" {
  description = "Fargate task CPU units (used by deploy.py when registering the task definition)."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task memory MiB."
  type        = number
  default     = 1024
}

variable "schedule_expression" {
  description = "Daily run time in schedule_timezone. Default 00:00 KST (2026-10-23 lemin), right after the KST day closed."
  type        = string
  default     = "cron(0 0 * * ? *)"
}

# 2026-10-23 lemin: 주문 시뮬레이터가 KST 벽시계 시각을 UTC 처럼 RDS 에 넣으므로, 하루가 끝나는 시점도 KST 0시로 맞춘다
variable "schedule_timezone" {
  description = "IANA time zone of schedule_expression."
  type        = string
  default     = "Asia/Seoul"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "keep_images" {
  description = "How many ECR images to keep."
  type        = number
  default     = 10
}

variable "alarm_email" {
  description = "Email for failed-run alerts. Empty = no SNS topic/alarm. Supply via *.local.tfvars."
  type        = string
  default     = ""
  sensitive   = true
}

variable "budget_email" {
  description = "Email for the monthly budget. Empty = no budget. Supply via *.local.tfvars."
  type        = string
  default     = ""
  sensitive   = true
}

variable "budget_limit_usd" {
  type    = number
  default = 10
}

variable "bedrock_price_input" {
  description = "USD per 1M input tokens for the dashboard estimate (gemma-3-12b Tokyo, src/rsim/bench/prices.json)."
  type        = number
  default     = 0.11
}

variable "bedrock_price_output" {
  description = "USD per 1M output tokens for the dashboard estimate."
  type        = number
  default     = 0.35
}

variable "config_parameter_name" {
  description = "SSM parameter the deploy scripts read."
  type        = string
  default     = "/clothes-query/dev/ecs-review-simulator/config"
}
