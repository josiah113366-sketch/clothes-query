data "terraform_remote_state" "eks" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = "ap-northeast-1", key = "clothes-query/dev/eks/terraform.tfstate" }
}
data "terraform_remote_state" "storage" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = "ap-northeast-1", key = "clothes-query/dev/storage/terraform.tfstate" }
}
module "collector" {
  source       = "../../modules/bronze-lag-collector"
  cluster_name = data.terraform_remote_state.eks.outputs.cluster_name
  bucket_arn   = data.terraform_remote_state.storage.outputs.bucket_arn
}
