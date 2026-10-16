variable "name" { type = string }
variable "enable_connect_repository" {
  description = "Add a separate Connect image repository without replacing WEB/WAS."
  type        = bool
  default     = false
}
