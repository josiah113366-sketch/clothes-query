# ecs-simulator stack: ECS Fargate for the trade/member simulator (owner: sim, applied by the owner).
# VPC/subnets and the data bucket come from the network and storage stacks, so no IDs are written here.
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
