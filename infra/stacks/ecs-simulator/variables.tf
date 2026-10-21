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
  description = "Team state bucket (same as deployment.backend.hcl). Used to read network/storage outputs."
  type        = string
  sensitive   = true
}
variable "state_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "image_digest" {
  description = "sha256:... of the pushed simulator image. Empty on the first apply (base only)."
  type        = string
  default     = ""
}
variable "api_url" {
  description = "Internal ALB URL of the business API. Supply in deployment.local.tfvars (endpoint)."
  type        = string
  default     = ""
  sensitive   = true
}
variable "desired_count" {
  type    = number
  default = 1
}
