variable "name" { type = string }
variable "app_subnet_ids" { type = list(string) }
variable "kubernetes_version" { type = string }
variable "admin_role_arns" {
  type = set(string)
  validation {
    condition     = length(var.admin_role_arns) > 0
    error_message = "Provide at least one explicitly approved administrator role."
  }
}
variable "public_access_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.public_access_cidrs) > 0 && alltrue([for c in var.public_access_cidrs : can(cidrnetmask(c)) && try(tonumber(split("/", c)[1]) >= 24, false)])
    error_message = "Provide administrator IPv4 ranges /24 or narrower; do not use a public /0."
  }
}
