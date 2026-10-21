variable "name" {
  description = "Resource name prefix (clothes-query-<env>-<purpose>)."
  type        = string
  default     = "clothes-query-dev-ecs-simulator"
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
  description = "Team data lake bucket (storage stack output). Controller incident log goes to ground_truth/incident_log/."
  type        = string
  sensitive   = true
}

variable "bucket_arn" {
  type      = string
  sensitive = true
}

variable "image_digest" {
  description = "Simulator image digest in this stack's ECR (sha256:...). Empty = create only the base (no task definition/service)."
  type        = string
  default     = ""
  validation {
    condition     = var.image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be empty or sha256:<64 hex>."
  }
}

variable "api_url" {
  description = "Business API base URL via the internal ALB (http://internal-...). Endpoint, so supply privately."
  type        = string
  default     = ""
  sensitive   = true
}

variable "desired_count" {
  description = "Running simulator tasks. 1 = on, 0 = stopped. Never more than 1 (traffic and answer key would double)."
  type        = number
  default     = 1
  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be 0 or 1."
  }
}

variable "cpu" {
  description = "Fargate task CPU units for all three containers together."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task memory MiB."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "keep_images" {
  description = "How many ECR images to keep."
  type        = number
  default     = 10
}
