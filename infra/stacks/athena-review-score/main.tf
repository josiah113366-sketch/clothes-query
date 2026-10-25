# athena-review-score 스택 (초안): 리뷰 점수 결과를 Iceberg 테이블로 관리하는 Athena/Glue 기반.
# 담당: 리뷰 분석(review-model) 담당 lemin 이 작성, apply 는 인프라 담당(재영)이 plan 확인 후 실행한다(infra/CLAUDE.md).
# 데이터 버킷은 storage 스택이 이미 만들었다. 값은 remote state 로 받고 이 파일에는 이름을 쓰지 않는다.

data "terraform_remote_state" "storage" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/storage/terraform.tfstate"
  }
}

module "athena_review_score" {
  source = "../../modules/athena-review-score"

  name      = "clothes-query-dev-athena-review-score"
  component = "athena-review-score"
  region    = var.aws_region

  # storage 스택: 팀 데이터 버킷. staging(읽기), Iceberg 테이블 위치(읽기/쓰기/삭제), Athena 결과 위치(읽기/쓰기)만 쓴다.
  bucket_name    = data.terraform_remote_state.storage.outputs.bucket_name
  bucket_arn     = data.terraform_remote_state.storage.outputs.bucket_arn
  staging_prefix = var.staging_prefix
  table_prefix   = var.table_prefix
  results_prefix = var.results_prefix

  silver_reviews_prefix          = var.silver_reviews_prefix
  silver_reviews_runs_table_name = var.silver_reviews_runs_table_name

  staging_log_prefix     = var.staging_log_prefix
  log_table_prefix       = var.log_table_prefix
  log_table_name         = var.log_table_name
  staging_log_table_name = var.staging_log_table_name

  database_name      = var.database_name
  table_name         = var.table_name
  staging_table_name = var.staging_table_name
  latest_view_name   = var.latest_view_name
  status_view_name   = var.status_view_name

  comparison_model_versions = var.comparison_model_versions
  bytes_scanned_cutoff      = var.bytes_scanned_cutoff
}
