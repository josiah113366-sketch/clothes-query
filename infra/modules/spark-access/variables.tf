variable "enabled" {
  type    = bool
  default = false
}
variable "enable_review_access" {
  description = "Opt-in confirmed review sources, outputs and read-only latest-score lookup."
  type        = bool
  default     = false
}
variable "review_rollback_run_ids" {
  type    = set(string)
  default = []
  validation {
    condition     = alltrue([for id in var.review_rollback_run_ids : can(regex("^[A-Za-z0-9_-]{1,100}$", id))])
    error_message = "Use literal approved review run IDs."
  }
}
variable "enable_funnel_access" {
  description = "Opt-in confirmed clickstream input, clicks/funnels outputs and two existing Gold A tables."
  type        = bool
  default     = false
}
variable "funnel_rollback_run_ids" {
  description = "Approved funnel run IDs whose partially committed Parquet files may be rolled back."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for id in var.funnel_rollback_run_ids : can(regex("^[A-Za-z0-9_-]{1,100}$", id))])
    error_message = "Use literal funnel run IDs without wildcards or path separators."
  }
}
variable "enable_trade_publication" {
  description = "Opt-in Silver/Gold trade publication and narrowly scoped R6 reads; does not grant schema creation or reviews access."
  type        = bool
  default     = false
}
variable "detection_role_name" {
  type    = string
  default = "clothes-query-dev-detection-job"
  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]+$", var.detection_role_name))
    error_message = "Use an existing IAM role name, not an ARN or wildcard."
  }
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
variable "reference_object_arns" {
  description = "Confirmed read-only product snapshot objects; no wildcard/bucket write grant."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([for arn in var.reference_object_arns : contains([
      "arn:aws:s3:::hm-ecommerce-data/seed_v2/product_design/product_design.parquet",
      "arn:aws:s3:::hm-ecommerce-data/seed_v2/product_variant/product_variant.parquet"
    ], arn)])
    error_message = "Use only the two confirmed product snapshot objects."
  }
}
variable "rollback_run_ids" {
  description = "Explicit approved run IDs whose final Parquet parts may be cleaned after a failed commit."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for id in var.rollback_run_ids : can(regex("^[A-Za-z0-9_-]{1,100}$", id))])
    error_message = "Use literal run IDs without wildcard or path separators."
  }
}
