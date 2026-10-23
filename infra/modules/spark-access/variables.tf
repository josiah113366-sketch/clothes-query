variable "enabled" {
  type    = bool
  default = false
}
variable "cluster_name" { type = string }
variable "bucket_arn" { type = string }
variable "namespace" {
  type     = string
  default  = null
  nullable = true
  validation {
    condition     = !var.enabled || can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    error_message = "Confirm the namespace before enabling Spark data access."
  }
}
variable "service_account_prefix" {
  type    = string
  default = "silver-gold-a"
  validation {
    condition     = length(var.service_account_prefix) <= 32 && can(regex("^[a-z][a-z0-9-]*$", var.service_account_prefix))
    error_message = "Use a lowercase ServiceAccount prefix of at most 32 characters."
  }
}
variable "read_prefixes" {
  type = set(string)
  default = [
    "bronze/orders/", "bronze/order-items/", "bronze/payments/",
    "pipelines/requests/", "pipelines/input-manifests/"
  ]
  validation {
    condition = alltrue([for p in var.read_prefixes :
      can(regex("^[A-Za-z0-9][A-Za-z0-9/_.=-]*/$", p)) && !strcontains(p, "//") &&
      !contains(split("/", p), "..") && !contains(split("/", p), ".") &&
      anytrue([for root in ["bronze/orders/", "bronze/order-items/", "bronze/payments/", "pipelines/requests/", "pipelines/input-manifests/"] : startswith(p, root)])
    ])
    error_message = "Use literal prefixes within the supplied trade inputs and request/manifest roots only."
  }
}
variable "output_prefixes" {
  type    = set(string)
  default = ["silver/runtime/trade/", "gold_a/runtime/trade/"]
  validation {
    condition = length(var.output_prefixes) > 0 && alltrue([for p in var.output_prefixes :
      can(regex("^[A-Za-z0-9][A-Za-z0-9/_.=-]*/$", p)) && !strcontains(p, "//") &&
      !contains(split("/", p), "..") && !contains(split("/", p), ".") &&
      (startswith(p, "silver/runtime/trade/") || startswith(p, "gold_a/runtime/trade/"))
    ])
    error_message = "Keep outputs within the supplied trade roots; do not infer funnels/reviews access."
  }
}
variable "allow_bucket_multipart_listing" {
  description = "Optional bucket-level multipart metadata listing; confirm the committer setting before enabling."
  type        = bool
  default     = false
}
variable "s3_endpoint_actions" {
  type    = set(string)
  default = []
}
