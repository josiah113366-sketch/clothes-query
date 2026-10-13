data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/eks/terraform.tfstate"
  }
}

data "terraform_remote_state" "rds" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/rds/terraform.tfstate"
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
data "terraform_remote_state" "compute" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/compute/terraform.tfstate"
  }
}
module "apps" {
  source                 = "../../modules/apps"
  name                   = "clothes-query-dev-apps"
  namespace              = var.namespace
  cluster_name           = data.terraform_remote_state.eks.outputs.cluster_name
  bucket_name            = data.terraform_remote_state.storage.outputs.bucket_name
  bucket_arn             = data.terraform_remote_state.storage.outputs.bucket_arn
  database_address       = data.terraform_remote_state.rds.outputs.address
  database_name          = data.terraform_remote_state.rds.outputs.database_name
  region                 = var.aws_region
  s3_prefix              = var.s3_prefix
  deploy_workloads       = var.deploy_workloads
  images                 = var.images
  database_secret_name   = var.database_secret_name
  certificate_arn        = var.certificate_arn
  hostname               = var.hostname
  alb_inbound_cidrs      = var.alb_inbound_cidrs
  node_pool_name         = data.terraform_remote_state.compute.outputs.node_pool_name
  workload_settings      = var.workload_settings
  was_autoscaling        = var.was_autoscaling
  metrics_server_version = var.metrics_server_version
}
