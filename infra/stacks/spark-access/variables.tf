variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "expected_account_id" {
  type      = string
  sensitive = true
}
variable "state_bucket" {
  type      = string
  sensitive = true
}
variable "enabled" {
  type    = bool
  default = false
}
variable "namespace" {
  type     = string
  default  = null
  nullable = true
}
variable "service_account_prefix" {
  type    = string
  default = "silver-gold-a"
}
variable "allow_bucket_multipart_listing" {
  type    = bool
  default = false
}
variable "reference_object_arns" {
  type    = set(string)
  default = []
}
variable "rollback_run_ids" {
  type    = set(string)
  default = []
}
