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
  description = "Optional existing administrator roles in addition to the dedicated role."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for arn in var.admin_role_arns : can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$", arn))])
    error_message = "Provide explicit IAM role ARNs; users, root and STS sessions are not administrator roles."
  }
}

variable "public_access_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.public_access_cidrs) > 0 && alltrue([for c in var.public_access_cidrs : can(cidrnetmask(c)) && try(tonumber(split("/", c)[1]) >= 24, false)])
    error_message = "Provide administrator IPv4 ranges /24 or narrower; do not use a public /0."
  }
}

variable "admin_trusted_principal_arns" {
  description = "Explicit IAM users/roles permitted to assume the dedicated EKS administrator role. Keep real ARNs in private inputs."
  type        = set(string)
  validation {
    condition     = length(var.admin_trusted_principal_arns) > 0 && alltrue([for arn in var.admin_trusted_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/[A-Za-z0-9_+=,.@/-]+$", arn))])
    error_message = "Trust only explicit IAM user/role ARNs; wildcard, root and STS session principals are forbidden."
  }
}
