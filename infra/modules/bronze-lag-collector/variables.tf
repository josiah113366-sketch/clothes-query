variable "name" {
  type    = string
  default = "clothes-query-dev"
}
variable "cluster_name" { type = string }
variable "bucket_arn" { type = string }
variable "namespace" {
  type    = string
  default = "pipelines"
  validation {
    condition     = var.namespace == "pipelines"
    error_message = "Use the confirmed pipelines namespace."
  }
}
