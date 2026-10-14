data "terraform_remote_state" "network" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = var.state_region, key = "clothes-query/dev/network/terraform.tfstate" }
}
data "terraform_remote_state" "eks" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = var.state_region, key = "clothes-query/dev/eks/terraform.tfstate" }
}
module "compute" {
  source                     = "../../modules/compute"
  name                       = "clothes-query-dev-compute"
  node_role_name             = data.terraform_remote_state.eks.outputs.node_role_name
  app_subnet_ids             = data.terraform_remote_state.network.outputs.workload_subnet_ids
  availability_zones         = [data.terraform_remote_state.network.outputs.workload_az]
  cluster_security_group_id  = data.terraform_remote_state.eks.outputs.cluster_security_group_id
  instance_types             = var.instance_types
  node_pool_cpu_limit        = var.node_pool_cpu_limit
  node_pool_memory_limit_gib = var.node_pool_memory_limit_gib
  consolidate_after          = var.consolidate_after
}
