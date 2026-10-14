variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "expected_account_id" {
  description = "Supply privately via TF_VAR_expected_account_id; prevents use of the wrong AWS account."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the approved AWS account ID privately."
  }
}

variable "state_bucket" {
  description = "Existing bootstrap bucket. Supply privately; never recreate bootstrap to obtain it."
  type        = string
  sensitive   = true
}
variable "state_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "namespace" {
  type    = string
  default = "clothes-query"
}

variable "s3_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9/_-]*/$", var.s3_prefix)) && !strcontains(var.s3_prefix, "//")
    error_message = "Provide a scoped prefix ending in /, for example application/."
  }
}

variable "deploy_workloads" {
  type    = bool
  default = false
}

variable "images" {
  type    = map(string)
  default = {}
  validation {
    condition     = !var.deploy_workloads || (contains(keys(var.images), "web") && contains(keys(var.images), "was") && alltrue([for image in values(var.images) : can(regex("@sha256:[0-9a-f]{64}$", image))]))
    error_message = "Deployment requires web and was images pinned by sha256 digest."
  }
}

variable "database_secret_name" {
  description = "Externally supplied Secret in this namespace with DB_USER and DB_PASSWORD; never the RDS master."
  type        = string
  default     = "was-database"
}

variable "certificate_arn" {
  type     = string
  default  = null
  nullable = true
  validation {
    condition     = !var.deploy_workloads || try(length(trimspace(var.certificate_arn)) > 0, false)
    error_message = "Provide a non-blank ACM certificate ARN before enabling HTTPS workloads."
  }
}

variable "hostname" {
  type     = string
  default  = null
  nullable = true
  validation {
    condition     = !var.deploy_workloads || try(length(trimspace(var.hostname)) > 0, false)
    error_message = "Provide a non-blank application DNS hostname before enabling workloads."
  }
}

variable "alb_inbound_cidrs" {
  type    = list(string)
  default = []
  validation {
    condition     = !var.deploy_workloads || (length(var.alb_inbound_cidrs) > 0 && alltrue([for c in var.alb_inbound_cidrs : can(cidrnetmask(c))]))
    error_message = "Explicitly specify allowed ALB IPv4 CIDRs."
  }
}

variable "workload_settings" {
  description = "WEB replicas and WEB/WAS resources. WAS replicas are managed by was_autoscaling."
  type = object({
    web = optional(object({
      replicas               = optional(number, 2)
      cpu_request_millicores = optional(number, 100)
      cpu_limit_millicores   = optional(number, 500)
      memory_request_mib     = optional(number, 128)
      memory_limit_mib       = optional(number, 512)
    }), {})
    was = optional(object({
      cpu_request_millicores = optional(number, 100)
      cpu_limit_millicores   = optional(number, 500)
      memory_request_mib     = optional(number, 128)
      memory_limit_mib       = optional(number, 512)
    }), {})
  })
  default = {}
  validation {
    condition = alltrue([for w in values(var.workload_settings) :
      try(w.replicas, 2) >= 2 &&
      w.cpu_request_millicores > 0 && w.cpu_limit_millicores >= w.cpu_request_millicores &&
      w.memory_request_mib > 0 && w.memory_limit_mib >= w.memory_request_mib &&
      alltrue([for n in values(w) : floor(n) == n])
    ])
    error_message = "Use integer resource amounts, replicas >= 2, and positive requests no greater than limits."
  }
}

variable "metrics_server_version" {
  description = "Pin the compatible EKS add-on version reviewed in the final plan; null selects the EKS default compatible version."
  type        = string
  default     = null
}
variable "was_autoscaling" {
  type = object({
    min_replicas                     = optional(number, 2)
    max_replicas                     = optional(number, 3)
    target_cpu_utilization           = optional(number, 70)
    scale_down_stabilization_seconds = optional(number, 300)
  })
  default = {}
  validation {
    condition     = var.was_autoscaling.min_replicas >= 2 && var.was_autoscaling.max_replicas >= var.was_autoscaling.min_replicas && var.was_autoscaling.target_cpu_utilization >= 1 && var.was_autoscaling.target_cpu_utilization <= 100 && var.was_autoscaling.scale_down_stabilization_seconds >= 0 && var.was_autoscaling.scale_down_stabilization_seconds <= 3600 && alltrue([for n in values(var.was_autoscaling) : floor(n) == n])
    error_message = "Use integers: 2 <= min <= max, CPU target 1..100, and stabilization 0..3600 seconds."
  }
}
