variable "name" { type = string }
variable "vpc_id" { type = string }
variable "db_subnet_ids" { type = list(string) }
variable "workload_security_group_id" {
  description = "Optional legacy EKS client security group; null creates no EKS ingress."
  type        = string
  default     = null
}
variable "database_clients" {
  description = "Explicit named EC2/ECS/other client security groups allowed PostgreSQL access."
  type        = map(string)
  default     = {}
  validation {
    condition     = alltrue([for sg in values(var.database_clients) : can(regex("^sg-[0-9a-f]+$", sg))])
    error_message = "Each client must reference an explicit security group ID."
  }
}
variable "engine_version" { type = string }
variable "logical_replication" {
  description = "Explicit CDC budgets; null keeps the existing default parameter-group behavior."
  type = object({
    max_replication_slots     = number
    max_wal_senders           = number
    max_slot_wal_keep_size_mb = number
  })
  default = null
  validation {
    condition = var.logical_replication == null ? true : alltrue([
      for value in values(var.logical_replication) : value > 0 && floor(value) == value
    ])
    error_message = "CDC requires explicit positive integer slot/sender counts and a finite WAL budget in MiB."
  }
  validation {
    condition = var.logical_replication == null ? true : (
      can(regex("^[1-9][0-9]*(\\.[0-9]+)*$", var.engine_version)) &&
      try(tonumber(split(".", var.engine_version)[0]) >= 13, false)
    )
    error_message = "CDC settings require an explicit PostgreSQL version >= 13; verify RDS family support before deployment."
  }
}
variable "instance_class" { type = string }
variable "allocated_storage" {
  type = number
  validation {
    condition     = var.allocated_storage >= 20 && floor(var.allocated_storage) == var.allocated_storage
    error_message = "Storage must be an integer of at least 20 GiB."
  }
}
variable "max_allocated_storage" {
  type = number
  validation {
    condition     = var.max_allocated_storage >= ceil(var.allocated_storage * 1.1)
    error_message = "Maximum storage must be at least 10 percent above initial storage."
  }
}
variable "database_name" {
  type    = string
  default = "clothes"
}

variable "availability_zone" { type = string }
