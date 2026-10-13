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
variable "kubernetes_version" { type = string }

variable "admin_role_arns" {
  type = set(string)
  validation {
    condition     = length(var.admin_role_arns) > 0
    error_message = "Provide at least one explicitly approved administrator role."
  }
}

variable "public_access_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.public_access_cidrs) > 0 && alltrue([for c in var.public_access_cidrs : can(cidrnetmask(c)) && try(tonumber(split("/", c)[1]) >= 24, false)])
    error_message = "Provide administrator IPv4 ranges /24 or narrower; do not use a public /0."
  }
}
