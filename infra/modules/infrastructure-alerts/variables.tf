variable "name" { type = string }
variable "cluster_name" { type = string }
variable "db_instance_identifier" { type = string }
variable "email_recipients" {
  type      = set(string)
  sensitive = true
  validation {
    condition     = length(var.email_recipients) >= 1 && length(var.email_recipients) <= 5 && alltrue([for email in var.email_recipients : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", email))])
    error_message = "Supply 1-5 email recipients privately."
  }
}
variable "wal_budget_mib" {
  type    = number
  default = 256
  validation {
    condition     = var.wal_budget_mib > 0
    error_message = "Use the configured RDS WAL budget in MiB."
  }
}
