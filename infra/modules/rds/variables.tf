variable "name" { type = string }
variable "vpc_id" { type = string }
variable "db_subnet_ids" { type = list(string) }
variable "workload_security_group_id" { type = string }
variable "engine_version" { type = string }
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
