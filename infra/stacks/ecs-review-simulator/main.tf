# ecs-review-simulator stack: ECS Fargate base for the review simulator (owner: review-sim, applied by the owner).
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
module "ecs_review_simulator" {
  source              = "../../modules/ecs-review-simulator"
  name                = "clothes-query-dev-ecs-review-simulator"
  region              = var.aws_region
  vpc_id              = data.terraform_remote_state.network.outputs.vpc_id
  subnet_ids          = data.terraform_remote_state.network.outputs.app_subnet_ids
  bucket_name         = data.terraform_remote_state.storage.outputs.bucket_name
  bucket_arn          = data.terraform_remote_state.storage.outputs.bucket_arn
  schedule_expression = var.schedule_expression
  alarm_email         = var.alarm_email
  budget_email        = var.budget_email
  budget_limit_usd    = var.budget_limit_usd
}
