variable "name" { type = string }
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
variable "region" { type = string }
variable "enable_nat_gateways" {
  description = "Create NAT egress in the selected mode. Disable for RDS-only operation."
  type        = bool
  default     = true
}
variable "single_nat_gateway" {
  description = "Share one NAT in the first sorted subnet key; false preserves one NAT per AZ."
  type        = bool
  default     = false
}
variable "additional_s3_endpoint_actions" {
  description = "Explicit optional transport actions; workload IAM remains separately scoped."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([for action in var.additional_s3_endpoint_actions : contains([
      "s3:GetObjectVersion", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:ListBucketMultipartUploads"
    ], action)])
    error_message = "Only explicit supported object/version/multipart actions may extend the endpoint policy."
  }
}
