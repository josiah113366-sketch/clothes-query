# ecs-simulator 스택: 거래·회원 시뮬레이터 ECS Fargate (담당: sim, 담당자가 apply).
# VPC·서브넷과 데이터 버킷은 network·storage 스택 state 에서 받으므로 여기에 ID를 적지 않는다.
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
module "ecs_simulator" {
  source        = "../../modules/ecs-simulator"
  name          = "clothes-query-dev-ecs-simulator"
  region        = var.aws_region
  vpc_id        = data.terraform_remote_state.network.outputs.vpc_id
  subnet_ids    = data.terraform_remote_state.network.outputs.app_subnet_ids
  bucket_name   = data.terraform_remote_state.storage.outputs.bucket_name
  bucket_arn    = data.terraform_remote_state.storage.outputs.bucket_arn
  image_digest  = var.image_digest
  api_url       = var.api_url
  desired_count = var.desired_count
}
