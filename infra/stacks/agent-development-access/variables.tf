variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "expected_account_id" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the approved account ID privately."
  }
}
variable "state_bucket" {
  type      = string
  sensitive = true
}
variable "trusted_principal_arns" {
  type      = set(string)
  sensitive = true
}
