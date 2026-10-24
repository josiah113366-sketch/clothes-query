variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the expected AWS account ID."
  }
}
variable "email_recipients" {
  type      = set(string)
  sensitive = true
}
variable "cluster_name" {
  type    = string
  default = "clothes-query-dev-eks"
}
variable "db_instance_identifier" {
  type    = string
  default = "clothes-query-dev-rds"
}
variable "wal_budget_mib" {
  type    = number
  default = 256
}
