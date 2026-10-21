data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = "ap-northeast-1"
    key    = "clothes-query/dev/network/terraform.tfstate"
  }
}
data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = "ap-northeast-1"
    key    = "clothes-query/dev/eks/terraform.tfstate"
  }
}
data "terraform_remote_state" "storage" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = "ap-northeast-1"
    key    = "clothes-query/dev/storage/terraform.tfstate"
  }
}
module "gold_b_access" {
  source                         = "../../modules/gold-b-access"
  cluster_name                   = data.terraform_remote_state.eks.outputs.cluster_name
  bucket_arn                     = data.terraform_remote_state.storage.outputs.bucket_arn
  s3_endpoint_actions            = data.terraform_remote_state.network.outputs.s3_endpoint_actions
  results_prefixes               = var.results_prefixes
  detection_write_prefixes       = var.detection_write_prefixes
  bytes_scanned_cutoff_per_query = var.bytes_scanned_cutoff_per_query
}
