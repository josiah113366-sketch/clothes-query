data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/network/terraform.tfstate"
  }
}
data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/eks/terraform.tfstate"
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
module "workload_access" {
  source              = "../../modules/workload-access"
  name                = "clothes-query-dev-data"
  cluster_name        = data.terraform_remote_state.eks.outputs.cluster_name
  bucket_arn          = data.terraform_remote_state.storage.outputs.bucket_arn
  s3_endpoint_actions = data.terraform_remote_state.network.outputs.s3_endpoint_actions
  bindings            = var.bindings
}
