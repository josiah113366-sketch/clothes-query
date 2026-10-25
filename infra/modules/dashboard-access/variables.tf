variable "cluster_name" { type = string }
variable "enable_pipeline_status_reads" {
  description = "Read-only dashboard access to the six confirmed pipeline status tables and their data."
  type        = bool
  default     = false
}
variable "model_registry_prefix" {
  description = "Read-only model release notes prefix in the existing data bucket."
  type        = string
  default     = "review-score/model-registry/releases/"
  validation {
    condition     = can(regex("^review-score/model-registry/[a-zA-Z0-9/_.=-]+/$", var.model_registry_prefix)) && !strcontains(var.model_registry_prefix, "..") && !strcontains(var.model_registry_prefix, "//")
    error_message = "Use a literal release prefix below review-score/model-registry/, ending in /."
  }
}
variable "bucket_arn" {
  type = string
  validation {
    condition     = can(regex("^arn:aws:s3:::[a-z0-9][a-z0-9.-]+$", var.bucket_arn))
    error_message = "Use an existing data bucket ARN without a prefix."
  }
}
variable "enable_gold_a_reads" {
  type    = bool
  default = false
}

variable "namespace" {
  type    = string
  default = "dashboard"
  validation {
    condition     = length(var.namespace) <= 63 && can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    error_message = "Use a Kubernetes namespace name."
  }
}
variable "service_account" {
  type    = string
  default = "approval-dashboard"
  validation {
    condition     = length(var.service_account) <= 63 && can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.service_account))
    error_message = "Use a Kubernetes ServiceAccount name."
  }
}
variable "workgroup_name" {
  type    = string
  default = "clothes-query-dev-dashboard"
  validation {
    condition     = var.workgroup_name != "primary" && can(regex("^[a-zA-Z0-9._-]{1,128}$", var.workgroup_name))
    error_message = "Use a dedicated Athena workgroup."
  }
}
variable "results_prefix" {
  type    = string
  default = "athena-results/dashboard/"
  validation {
    condition     = can(regex("^athena-results/[a-zA-Z0-9][a-zA-Z0-9/_.=-]*/$", var.results_prefix)) && !strcontains(var.results_prefix, "//") && !startswith(var.results_prefix, "athena-results/detection/") && !startswith(var.results_prefix, "athena-results/investigation/")
    error_message = "Use a separate literal prefix below athena-results/, ending in /."
  }
}
variable "bytes_scanned_cutoff_per_query" {
  type    = number
  default = 1073741824
  validation {
    condition     = var.bytes_scanned_cutoff_per_query >= 10485760 && floor(var.bytes_scanned_cutoff_per_query) == var.bytes_scanned_cutoff_per_query
    error_message = "Use an integer cutoff of at least 10MiB."
  }
}
variable "enable_review_score_reads" {
  description = "감성분석 모델 화면용 읽기 전용 정책(점수 테이블·점수 로그·최신 뷰·Silver 리뷰 실행 출력·실행 요약 JSON)을 추가한다."
  type        = bool
  default     = false
}
variable "review_score_database" {
  description = "감성분석 점수 Glue 데이터베이스 이름(athena-review-score 스택의 database_name)."
  type        = string
  default     = "clothes_query_dev_review_score"
  validation {
    condition     = can(regex("^[a-z0-9_]+$", var.review_score_database))
    error_message = "Use a Glue database name."
  }
}
