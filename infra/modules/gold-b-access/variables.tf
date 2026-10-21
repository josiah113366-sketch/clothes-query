variable "name" {
  type    = string
  default = "clothes-query-dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,30}$", var.name))
    error_message = "Use a lowercase project role prefix of at most 31 characters."
  }
}
variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
  validation {
    condition     = var.aws_region == "ap-northeast-1"
    error_message = "This preparation is scoped to Tokyo."
  }
}
variable "cluster_name" { type = string }
variable "workgroup_names" {
  type = map(string)
  default = {
    detection     = "clothes-query-dev-detection"
    investigation = "clothes-query-dev-investigation"
  }
  validation {
    condition = (
      toset(keys(var.workgroup_names)) == toset(["detection", "investigation"]) &&
      length(distinct(values(var.workgroup_names))) == 2 &&
      alltrue([for n in values(var.workgroup_names) : n != "primary" && can(regex("^[a-zA-Z0-9._-]{1,128}$", n))])
    )
    error_message = "Supply distinct detection/investigation workgroup names; primary is reserved."
  }
}
variable "s3_endpoint_actions" {
  type = set(string)
  validation {
    condition     = alltrue([for a in ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucket", "s3:GetBucketLocation"] : contains(var.s3_endpoint_actions, a)])
    error_message = "The network S3 endpoint must allow the required source/result operations."
  }
}
variable "bucket_arn" {
  type = string
  validation {
    condition     = can(regex("^arn:aws:s3:::[a-z0-9][a-z0-9.-]+$", var.bucket_arn))
    error_message = "Supply the existing data bucket ARN, without object prefix."
  }
}
variable "namespace" {
  type    = string
  default = "agent"
  validation {
    condition     = length(var.namespace) <= 63 && can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    error_message = "Use a Kubernetes namespace name."
  }
}
variable "results_prefixes" {
  type = map(string)
  default = {
    investigation = "athena-results/investigation/"
    detection     = "athena-results/detection/"
  }
  validation {
    condition = (
      toset(keys(var.results_prefixes)) == toset(["investigation", "detection"]) &&
      alltrue([for p in values(var.results_prefixes) : can(regex("^[a-zA-Z0-9][a-zA-Z0-9/_.=-]*/$", p)) && !strcontains(p, "//") && !startswith(p, "gold_b/") && !startswith(p, "ground_truth/")]) &&
      alltrue(flatten([for k, p in var.results_prefixes : [for other, q in var.results_prefixes : k == other || (!startswith(p, q) && !startswith(q, p))]]))
    )
    error_message = "Provide disjoint literal investigation/detection prefixes outside gold_b/ and ground_truth/, ending in /."
  }
}
variable "detection_write_prefixes" {
  description = "Explicit confirmed history object prefixes only; empty until writer contract is supplied. No delete or catalog mutations."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for p in var.detection_write_prefixes : can(regex("^gold_b/[a-zA-Z0-9][a-zA-Z0-9/_.=-]*/$", p)) && !strcontains(p, "//")])
    error_message = "History writes must name literal non-root paths below gold_b/, ending in /."
  }
}
variable "bytes_scanned_cutoff_per_query" {
  type    = number
  default = 1073741824
  validation {
    condition     = var.bytes_scanned_cutoff_per_query >= 10485760 && floor(var.bytes_scanned_cutoff_per_query) == var.bytes_scanned_cutoff_per_query
    error_message = "Use an integer scan cutoff of at least 10MiB."
  }
}

variable "enable_investigation_catalog" {
  description = "Create the separate investigation database after namespace agreement."
  type        = bool
  default     = false
}
variable "investigation_database_name" {
  type    = string
  default = "agent"
  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{0,254}$", var.investigation_database_name)) && var.investigation_database_name != "gold_b"
    error_message = "Use a separate lowercase Glue database name."
  }
}
variable "investigation_write_prefixes" {
  description = "Confirmed report/history paths under agent/; query results remain separately writable."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for p in var.investigation_write_prefixes : (p == "agent/" || can(regex("^agent/[a-zA-Z0-9][a-zA-Z0-9/_.=-]*/$", p))) && !strcontains(p, "//")])
    error_message = "Investigation data writes must remain in literal agent/ paths ending in /."
  }
}
