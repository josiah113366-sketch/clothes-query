variable "name" { type = string }
variable "node_role_name" { type = string }
variable "app_subnet_ids" { type = list(string) }
variable "cluster_security_group_id" { type = string }
variable "availability_zones" {
  type = list(string)
  validation {
    condition     = length(distinct(var.availability_zones)) == 2
    error_message = "Provide the two approved availability zones."
  }
}

variable "instance_types" {
  description = "Allowed Auto Mode instance types; verify availability and size before changing."
  type        = set(string)
  default     = ["m6i.large", "m7i.large"]
  validation {
    condition     = length(var.instance_types) > 0
    error_message = "At least one approved instance type is required."
  }
}
variable "node_pool_cpu_limit" {
  description = "Total NodePool vCPU budget, not desired replicas or a currency ceiling."
  type        = number
  default     = 8
  validation {
    condition     = var.node_pool_cpu_limit >= 4 && floor(var.node_pool_cpu_limit) == var.node_pool_cpu_limit
    error_message = "Keep at least 4 vCPUs for two baseline nodes; add replacement headroom."
  }
}
variable "node_pool_memory_limit_gib" {
  type    = number
  default = 32
  validation {
    condition     = var.node_pool_memory_limit_gib >= 16 && floor(var.node_pool_memory_limit_gib) == var.node_pool_memory_limit_gib
    error_message = "Keep at least 16 GiB for two baseline nodes; add replacement headroom."
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
