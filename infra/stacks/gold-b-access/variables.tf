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
variable "results_prefixes" { type = map(string) }
variable "workgroup_names" { type = map(string) }
variable "detection_write_prefixes" {
  type    = set(string)
  default = []
}
variable "bytes_scanned_cutoff_per_query" { type = number }
variable "enable_investigation_catalog" {
  type    = bool
  default = false
}
variable "investigation_database_name" {
  type    = string
  default = "agent"
}
variable "investigation_write_prefixes" {
  type    = set(string)
  default = []
}
variable "investigation_bedrock_profiles" {
  type = map(object({
    profile_arn = string
    model_arns  = set(string)
  }))
  default = {}
}
