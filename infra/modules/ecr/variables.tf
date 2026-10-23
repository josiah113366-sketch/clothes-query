variable "name" { type = string }
variable "enable_spark_repositories" {
  description = "Opt in to separate Spark base and Silver/Gold A business image repositories."
  type        = bool
  default     = false
}
variable "spark_publisher_user_arns" {
  description = "Developer IAM users allowed to push only the two Spark repositories. Not Pod execution identities."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([for arn in var.spark_publisher_user_arns :
      can(regex("^arn:aws:iam::[0-9]{12}:user/[A-Za-z0-9_+=,.@/-]+$", arn))
    ])
    error_message = "Supply explicit IAM user ARNs; role, wildcard and external principal policies are not inferred."
  }
  validation {
    condition     = var.enable_spark_repositories || length(var.spark_publisher_user_arns) == 0
    error_message = "Enable the Spark repositories before selecting their developer publishers."
  }
}
variable "enable_connect_repository" {
  description = "Add a separate Connect image repository without replacing WEB/WAS."
  type        = bool
  default     = false
}
