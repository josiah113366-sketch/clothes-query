variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the expected AWS account ID."
  }
}
variable "state_bucket" { type = string }
variable "enable_pipeline_status_reads" {
  type    = bool
  default = false
}
variable "enable_gold_a_reads" {
  type    = bool
  default = false
}
variable "model_registry_prefix" {
  type    = string
  default = "review-score/model-registry/releases/"
}
variable "namespace" { type = string }
variable "service_account" { type = string }
variable "workgroup_name" { type = string }
variable "results_prefix" { type = string }
variable "bytes_scanned_cutoff_per_query" { type = number }
