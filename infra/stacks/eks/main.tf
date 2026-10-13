data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.state_region
    key    = "clothes-query/dev/network/terraform.tfstate"
  }
}
module "eks" {
  source              = "../../modules/eks"
  name                = "clothes-query-dev-eks"
  app_subnet_ids      = data.terraform_remote_state.network.outputs.app_subnet_ids
  kubernetes_version  = var.kubernetes_version
  admin_role_arns     = var.admin_role_arns
  public_access_cidrs = var.public_access_cidrs
}
