data "terraform_remote_state" "eks" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = var.aws_region, key = "clothes-query/dev/eks/terraform.tfstate" }
}
data "terraform_remote_state" "storage" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = var.aws_region, key = "clothes-query/dev/storage/terraform.tfstate" }
}
data "terraform_remote_state" "network" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = var.aws_region, key = "clothes-query/dev/network/terraform.tfstate" }
}
module "spark_access" {
  source                         = "../../modules/spark-access"
  enabled                        = var.enabled
  namespace                      = var.namespace
  service_account_prefix         = var.service_account_prefix
  cluster_name                   = data.terraform_remote_state.eks.outputs.cluster_name
  bucket_arn                     = data.terraform_remote_state.storage.outputs.bucket_arn
  s3_endpoint_actions            = data.terraform_remote_state.network.outputs.s3_endpoint_actions
  allow_bucket_multipart_listing = var.allow_bucket_multipart_listing
  reference_object_arns          = var.reference_object_arns
  rollback_run_ids               = var.rollback_run_ids
  enable_trade_publication       = var.enable_trade_publication
  detection_role_name            = var.detection_role_name
}
