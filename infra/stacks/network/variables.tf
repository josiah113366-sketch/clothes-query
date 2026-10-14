variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "additional_s3_endpoint_actions" {
  type    = set(string)
  default = []
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
variable "vpc_cidr" {
  type = string
  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "Provide an IPv4 VPC CIDR."
  }
}

variable "subnets" {
  description = "Exactly two AZs, each with public/app/db IPv4 CIDRs."
  type = map(object({
    az          = string
    public_cidr = string
    app_cidr    = string
    db_cidr     = string
  }))
  validation {
    condition     = length(var.subnets) == 2 && length(distinct([for s in values(var.subnets) : s.az])) == 2
    error_message = "HA requires exactly two distinct availability zones."
  }
  validation {
    condition     = alltrue(flatten([for s in values(var.subnets) : [for c in [s.public_cidr, s.app_cidr, s.db_cidr] : can(cidrnetmask(c))]]))
    error_message = "All subnet CIDRs must be valid IPv4 ranges."
  }
}
