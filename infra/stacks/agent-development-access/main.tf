data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.aws_region
    key    = "clothes-query/dev/eks/terraform.tfstate"
  }
}
module "agent_development_access" {
  source                 = "../../modules/agent-development-access"
  name                   = "clothes-query-dev"
  cluster_name           = data.terraform_remote_state.eks.outputs.cluster_name
  trusted_principal_arns = var.trusted_principal_arns
}
