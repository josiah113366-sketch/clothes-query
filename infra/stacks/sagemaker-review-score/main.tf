# sagemaker-review-score 스택: 리뷰 점수화(s2c 모델) SageMaker Processing Job 실행 기반.
# 담당: 리뷰 분석(review-model) 담당 lemin 이 작성, apply 는 인프라 담당(재영)이 plan 확인 후 실행한다(infra/CLAUDE.md).
# VPC·subnet 과 데이터 버킷은 network / storage 스택이 이미 만들었다. 값은 remote state 로 받고 이 파일에는 ID 를 쓰지 않는다.

data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/network/terraform.tfstate"
  }
}

data "terraform_remote_state" "storage" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/storage/terraform.tfstate"
  }
}

module "sagemaker_review_score" {
  source = "../../modules/sagemaker-review-score"

  name      = "clothes-query-dev-sagemaker-review-score"
  component = "sagemaker-review-score"
  region    = var.aws_region

  # network 스택: Job 이 뜰 app subnet(NAT 경유). use_vpc=false 면 vpc_id/subnet 은 쓰이지 않는다.
  use_vpc    = var.use_vpc
  vpc_id     = data.terraform_remote_state.network.outputs.vpc_id
  subnet_ids = data.terraform_remote_state.network.outputs.app_subnet_ids

  # storage 스택: 팀 데이터 버킷. 입력 silver/reviews/ 읽기, 모델·코드 review-score/ 읽기, 결과 silver/review_aspect_scores/·오류 silver/review_aspect_scores_error/ 쓰기.
  bucket_name         = data.terraform_remote_state.storage.outputs.bucket_name
  bucket_arn          = data.terraform_remote_state.storage.outputs.bucket_arn
  review_input_prefix = var.review_input_prefix
  work_prefix         = var.work_prefix
  output_prefix       = var.output_prefix
  error_prefix        = var.error_prefix
  model_version       = var.model_version

  instance_type       = var.instance_type
  max_runtime_seconds = var.max_runtime_seconds

}
