variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Supply the expected AWS account ID."
  }
}
variable "monthly_budget_usd" { type = number }
variable "email_recipients" {
  type      = set(string)
  sensitive = true
}
