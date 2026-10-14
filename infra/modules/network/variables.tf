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
    error_message = "AWS EKS, ALB and RDS subnet groups require two distinct availability zones."
  }
  validation {
    condition     = alltrue(flatten([for s in values(var.subnets) : [for c in [s.public_cidr, s.app_cidr, s.db_cidr] : can(cidrnetmask(c))]]))
    error_message = "All subnet CIDRs must be valid IPv4 ranges."
  }
}
variable "region" { type = string }

variable "workload_az" {
  description = "Single AZ for NAT, worker nodes and RDS; second-zone subnets remain for AWS service requirements."
  type        = string
  default     = "ap-northeast-1a"
  validation {
    condition     = contains([for s in values(var.subnets) : s.az], var.workload_az)
    error_message = "The workload AZ must exist in the subnet map."
  }
}
