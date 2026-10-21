variable "cluster_name" { type = string }
variable "principal_arn" {
  description = "Explicit teammate IAM user or role ARN, supplied privately; never use an STS session or administrator role trust."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/[A-Za-z0-9_+=,.@/-]+$", var.principal_arn))
    error_message = "Supply an explicit IAM user or role ARN, not root, a wildcard or an STS session."
  }
}
variable "namespace" {
  type    = string
  default = "clothes-query"
  validation {
    condition     = var.namespace == "clothes-query"
    error_message = "This binding is restricted to the existing application's planned namespace clothes-query."
  }
}
