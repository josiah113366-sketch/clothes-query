variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "name" {
  description = "Resource name prefix shared with the other dev stacks."
  type        = string
  default     = "clothes-query-dev"
}
variable "expected_account_id" {
  description = "Approved AWS account ID; prevents use of the wrong AWS account. Shared via deployment.auto.tfvars.json."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the approved AWS account ID."
  }
}
