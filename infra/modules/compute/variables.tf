variable "name" { type = string }
variable "spark_node_pool" {
  description = "Opt-in Spark pool; disabled creates no resource. Sizing is a development candidate, not a measured guarantee."
  type = object({
    enabled           = optional(bool, false)
    instance_types    = optional(set(string), ["t3a.medium"])
    cpu_limit         = optional(number, 4)
    memory_limit_gib  = optional(number, 8)
    consolidate_after = optional(string, "10m")
  })
  default = {}
  validation {
    condition = length(var.spark_node_pool.instance_types) > 0 && alltrue([
      for t in var.spark_node_pool.instance_types : contains(["t3a.medium", "t3a.large", "m6a.large", "r6a.large"], t)
    ])
    error_message = "Choose explicitly sized amd64 development types: t3a.medium, t3a.large, m6a.large or r6a.large."
  }
  validation {
    condition     = var.spark_node_pool.cpu_limit >= 2 && floor(var.spark_node_pool.cpu_limit) == var.spark_node_pool.cpu_limit && var.spark_node_pool.memory_limit_gib >= 4 && floor(var.spark_node_pool.memory_limit_gib) == var.spark_node_pool.memory_limit_gib
    error_message = "Use integer capacity budgets of at least 2 vCPU and 4 GiB."
  }
  validation {
    condition = alltrue([
      for t in var.spark_node_pool.instance_types : var.spark_node_pool.memory_limit_gib >= lookup({ "t3a.medium" = 4, "t3a.large" = 8, "m6a.large" = 8, "r6a.large" = 16 }, t, 4)
    ])
    error_message = "The memory budget must fit at least one permitted instance."
  }
  validation {
    condition     = can(regex("^[1-9][0-9]*(s|m|h)$", var.spark_node_pool.consolidate_after))
    error_message = "Use a positive Spark empty-node consolidation duration."
  }
}
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
