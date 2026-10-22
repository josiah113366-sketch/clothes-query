variable "aws_region" {
  description = "리전. 팀 기준 도쿄."
  type        = string
  default     = "ap-northeast-1"
}

variable "expected_account_id" {
  description = "공유 배포 설정 deployment.auto.tfvars.json 의 값(자동 로드). 잘못된 AWS 계정 사용을 막는다."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "승인된 팀 AWS 계정 ID(12자리)가 필요하다. deployment.auto.tfvars.json 을 확인한다."
  }
}

variable "state_bucket" {
  description = "팀 state 버킷(deployment.backend.hcl 의 bucket 과 같은 값). storage output 을 읽는 데 쓴다. 공유 배포 설정 deployment.auto.tfvars.json 에 있다."
  type        = string
  sensitive   = true
}

variable "state_region" {
  description = "state 버킷 리전."
  type        = string
  default     = "ap-northeast-1"
}

variable "staging_prefix" {
  description = "SageMaker Job 이 점수 Parquet 을 임시로 쓰는 prefix(MERGE 입력). year=/month=/day= 하위 구조."
  type        = string
  default     = "staging/review-score"
}

variable "table_prefix" {
  description = "Iceberg 테이블 위치. Iceberg 가 data/·metadata/ 를 스스로 관리하므로 직접 파일을 넣지 않는다."
  type        = string
  default     = "silver/review_aspect_scores_iceberg"
}

variable "staging_log_prefix" {
  description = "후기별 점수 로그 staging prefix. sagemaker-review-score 스택의 score_log_prefix 와 같아야 한다."
  type        = string
  default     = "staging/review-score-log"
}

variable "log_table_prefix" {
  description = "점수 로그 Iceberg 테이블 위치."
  type        = string
  default     = "silver/review_score_log_iceberg"
}

variable "log_table_name" {
  description = "후기별 점수 로그 Iceberg 테이블 이름(Terraform 이 생성)."
  type        = string
  default     = "review_score_log"
}

variable "staging_log_table_name" {
  description = "점수 로그 staging 외부 테이블 이름(Terraform 이 생성)."
  type        = string
  default     = "staging_review_score_log"
}

variable "results_prefix" {
  description = "Athena 쿼리 결과 prefix."
  type        = string
  default     = "athena-results/review-score"
}

variable "database_name" {
  description = "Glue 데이터베이스 이름(소문자·숫자·밑줄)."
  type        = string
  default     = "clothes_query_dev_review_score"
}

variable "table_name" {
  description = "Iceberg 테이블 이름(Terraform 이 생성)."
  type        = string
  default     = "review_aspect_scores"
}

variable "staging_table_name" {
  description = "staging Parquet 을 읽는 Hive 외부 테이블 이름(Terraform 이 생성)."
  type        = string
  default     = "staging_review_aspect_scores"
}

variable "bytes_scanned_cutoff" {
  description = "쿼리당 스캔 한도(바이트, 최소 10MB). 기본 10GB."
  type        = number
  default     = 10737418240
}
