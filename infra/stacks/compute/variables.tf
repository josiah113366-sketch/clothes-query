variable "aws_region" { type = string }
variable "spark_node_pool" {
  description = "Optional Spark capacity; omitted/disabled leaves the existing pool unchanged."
  type = object({
    enabled           = optional(bool, false)
    instance_types    = optional(set(string), ["t3a.medium"])
    cpu_limit         = optional(number, 4)
    memory_limit_gib  = optional(number, 8)
    consolidate_after = optional(string, "10m")
  })
  default = {}
}
variable "expected_account_id" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the approved account ID privately."
  }
}
variable "state_bucket" {
  type      = string
  sensitive = true
}
variable "state_region" {
  type    = string
  default = "ap-northeast-1"
}

variable "instance_types" {
  description = "Allowed Auto Mode instance types; verify availability and size before changing."
  type        = set(string)
  default     = ["t3a.large"]
  validation {
    condition     = length(var.instance_types) > 0
    error_message = "At least one approved instance type is required."
  }
}
variable "node_pool_cpu_limit" {
  description = "Total NodePool vCPU budget, not desired replicas or a currency ceiling."
  type        = number
  default     = 6
  validation {
    condition     = var.node_pool_cpu_limit >= 4 && floor(var.node_pool_cpu_limit) == var.node_pool_cpu_limit
    error_message = "Keep at least 4 vCPUs for one baseline node plus replacement headroom."
  }
}
variable "node_pool_memory_limit_gib" {
  type    = number
  default = 24
  validation {
    condition     = var.node_pool_memory_limit_gib >= 16 && floor(var.node_pool_memory_limit_gib) == var.node_pool_memory_limit_gib
    error_message = "Keep at least 16 GiB for one baseline node plus replacement headroom."
  }
}
variable "consolidate_after" {
  description = "Wait before consolidating empty or underutilized nodes."
  type        = string
  default     = "10m"
  validation {
    condition     = can(regex("^[1-9][0-9]*(s|m|h)$", var.consolidate_after))
    error_message = "Use a positive duration such as 10m or 1h."
  }
}
