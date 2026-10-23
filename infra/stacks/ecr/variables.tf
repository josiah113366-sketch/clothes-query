variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "enable_connect_repository" {
  type    = bool
  default = false
}
variable "enable_gold_b_repository" {
  type    = bool
  default = false
}
variable "enable_spark_repositories" {
  type    = bool
  default = false
}
variable "spark_publisher_user_arns" {
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
