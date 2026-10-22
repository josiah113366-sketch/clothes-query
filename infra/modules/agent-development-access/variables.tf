variable "name" { type = string }
variable "cluster_name" { type = string }
variable "trusted_principal_arns" {
  type = set(string)
  validation {
    condition     = length(var.trusted_principal_arns) > 0 && alltrue([for arn in var.trusted_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/[A-Za-z0-9_+=,.@/-]+$", arn))])
    error_message = "Trust explicit IAM users or roles only."
  }
}
variable "repository_names" {
  type    = set(string)
  default = ["detection-job", "investigation-agent"]
  validation {
    condition     = length(var.repository_names) > 0 && alltrue([for name in var.repository_names : can(regex("^[a-z][a-z0-9-]+$", name))])
    error_message = "Use explicit lowercase image repository suffixes."
  }
}
