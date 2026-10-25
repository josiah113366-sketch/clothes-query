data "terraform_remote_state" "eks" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = "ap-northeast-1", key = "clothes-query/dev/eks/terraform.tfstate" }
}
data "terraform_remote_state" "storage" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = "ap-northeast-1", key = "clothes-query/dev/storage/terraform.tfstate" }
}
module "dashboard_access" {
  source                         = "../../modules/dashboard-access"
  cluster_name                   = data.terraform_remote_state.eks.outputs.cluster_name
  bucket_arn                     = data.terraform_remote_state.storage.outputs.bucket_arn
  namespace                      = var.namespace
  service_account                = var.service_account
  enable_pipeline_status_reads   = var.enable_pipeline_status_reads
  enable_gold_a_reads            = var.enable_gold_a_reads
  model_registry_prefix          = var.model_registry_prefix
  workgroup_name                 = var.workgroup_name
  results_prefix                 = var.results_prefix
  bytes_scanned_cutoff_per_query = var.bytes_scanned_cutoff_per_query
}
