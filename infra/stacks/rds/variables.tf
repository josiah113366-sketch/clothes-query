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
