variable "name" { type = string }

variable "monthly_budget_usd" {
  type = number
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "Set a positive, explicitly agreed monthly USD alert threshold."
  }
}

variable "email_recipients" {
  type      = set(string)
  sensitive = true
  validation {
    condition     = length(var.email_recipients) >= 1 && length(var.email_recipients) <= 5 && alltrue([for email in var.email_recipients : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", email))])
    error_message = "Supply 1-5 valid email recipients through private variables."
  }
}
