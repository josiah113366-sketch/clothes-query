variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "expected_account_id" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the approved AWS account ID privately."
  }
}
variable "state_bucket" {
  type      = string
  sensitive = true
}
variable "state_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "bindings" {
  type = map(object({
    namespace       = string
    service_account = string
    s3_access       = map(set(string))
  }))
  default = {}
}
