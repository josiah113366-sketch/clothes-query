variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
  validation {
    condition     = var.aws_region == "ap-northeast-1"
    error_message = "Team access changes are limited to Tokyo."
  }
}
variable "expected_account_id" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the approved shared account ID privately."
  }
}
variable "state_bucket" {
  type      = string
  sensitive = true
}
variable "principal_arn" {
  type      = string
  sensitive = true
}
