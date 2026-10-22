# 입력 변수. 스택(stacks/athena-review-score)이 값을 넘긴다. (초안: 2026-10-22, 작업 지시서 docs/tasks/infra-athena-review-score.md)
# 계정 ID·버킷 이름 같은 비공개 값은 기본값으로 두지 않는다(공개 저장소). 스택이 storage 스택 state 에서 받아 넘긴다.

variable "name" {
  description = "리소스 이름 접두사. 팀 규칙: clothes-query-<환경>-<용도>."
  type        = string
  default     = "clothes-query-dev-athena-review-score"
}

variable "component" {
  description = "비용 할당 태그 Component 값."
  type        = string
  default     = "athena-review-score"
}

variable "region" {
  description = "리전. 팀 기준은 도쿄(ap-northeast-1)."
  type        = string
  default     = "ap-northeast-1"
}

# ------------------------------------------------------------------ S3 (storage 스택 output)

variable "bucket_name" {
  description = "팀 데이터 버킷 이름(storage 스택 output). 민감 값이라 코드에 쓰지 않는다."
  type        = string
}

variable "bucket_arn" {
  description = "팀 데이터 버킷 ARN(storage 스택 output)."
  type        = string
}

variable "staging_prefix" {
  description = <<-EOT
    SageMaker Job 이 점수 결과(Parquet)를 임시로 쓰는 prefix. 테이블이 아니라 "MERGE 의 입력"이다.
    Job 이 <staging_prefix>/year=YYYY/month=MM/day=DD/scores_<model_version>_<실행시각>.parquet 로 쓰고, Athena 의 Hive 외부 테이블이 이를 읽는다.
    MERGE 로 테이블에 반영한 뒤에는 지워도 된다(정리는 Airflow 태스크 또는 별도 수명주기 규칙 — 열린 질문).
  EOT
  type        = string
  default     = "staging/review-score"
}

variable "table_prefix" {
  description = <<-EOT
    Iceberg 테이블이 데이터·메타데이터를 두는 위치(S3 prefix). Iceberg 가 이 아래 data/, metadata/ 를 스스로 관리하므로
    사람이 직접 파일을 넣거나 지우지 않는다. 이전 Parquet 시험 결과(silver/review_aspect_scores/)와 섞이지 않게 별도 prefix 를 쓴다.
  EOT
  type        = string
  default     = "silver/review_aspect_scores_iceberg"
}

variable "staging_log_prefix" {
  description = <<-EOT
    후기별 점수 로그를 Job 이 임시로 쓰는 prefix(<이 값>/year=/month=/day=/scorelog_<버전>_<실행시각>.parquet).
    sagemaker-review-score 스택의 score_log_prefix 와 같아야 한다. merge_log.sql 의 입력이다.
  EOT
  type        = string
  default     = "staging/review-score-log"
}

variable "log_table_prefix" {
  description = "점수 로그 Iceberg 테이블 위치(S3 prefix). 점수 테이블 위치와 겹치지 않게 별도 prefix 를 쓴다."
  type        = string
  default     = "silver/review_score_log_iceberg"
}

variable "results_prefix" {
  description = "Athena 쿼리 결과 파일이 쌓이는 prefix(워크그룹 설정). 쿼리마다 작은 파일이 생기므로 수명주기로 지우는 것을 권장(열린 질문)."
  type        = string
  default     = "athena-results/review-score"
}

# ------------------------------------------------------------------ Glue / Athena

variable "database_name" {
  description = "Glue 데이터베이스 이름. Athena 이름 규칙상 소문자·숫자·밑줄만 쓴다."
  type        = string
  default     = "clothes_query_dev_review_score"
}

variable "table_name" {
  description = "Iceberg 테이블 이름. Terraform(Glue 테이블 리소스)이 만든다."
  type        = string
  default     = "review_aspect_scores"
}

variable "log_table_name" {
  description = "후기별 점수 로그 Iceberg 테이블 이름. 점수가 하나도 안 나온 후기도 한 행 남아 select_unscored 가 같은 후기를 다시 고르지 않게 한다."
  type        = string
  default     = "review_score_log"
}

variable "staging_log_table_name" {
  description = "점수 로그 staging Parquet 을 읽는 Hive 외부 테이블 이름."
  type        = string
  default     = "staging_review_score_log"
}

variable "staging_table_name" {
  description = "staging Parquet 을 읽는 Hive 외부 테이블 이름. Terraform 이 만든다."
  type        = string
  default     = "staging_review_aspect_scores"
}

variable "bytes_scanned_cutoff" {
  description = "쿼리 하나가 스캔할 수 있는 최대 바이트(비용 안전장치). 최소 10,000,000 (10MB). 기본 10GB."
  type        = number
  default     = 10737418240
  validation {
    condition     = var.bytes_scanned_cutoff >= 10000000
    error_message = "Athena 워크그룹의 쿼리당 스캔 한도는 최소 10,000,000 바이트다."
  }
}

variable "config_parameter_name" {
  description = "Airflow/스크립트가 읽는 SSM 파라미터 이름. 다른 스택과 겹치지 않게 스택 이름을 넣는다."
  type        = string
  default     = "/clothes-query/dev/athena-review-score/config"
}
