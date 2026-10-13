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
module "rds" {
  source                     = "../../modules/rds"
  name                       = "clothes-query-dev-rds"
  vpc_id                     = data.terraform_remote_state.network.outputs.vpc_id
  db_subnet_ids              = data.terraform_remote_state.network.outputs.db_subnet_ids
  workload_security_group_id = data.terraform_remote_state.eks.outputs.cluster_security_group_id
  engine_version             = var.engine_version
  instance_class             = var.instance_class
  allocated_storage          = var.allocated_storage
  max_allocated_storage      = var.max_allocated_storage
  database_name              = var.database_name
  logical_replication        = var.logical_replication
}
