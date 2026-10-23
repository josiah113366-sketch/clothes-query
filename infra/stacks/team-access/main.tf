data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    region = var.aws_region
    key    = "clothes-query/dev/eks/terraform.tfstate"
  }
}

module "team_access" {
  source        = "../../modules/team-access"
  cluster_name  = data.terraform_remote_state.eks.outputs.cluster_name
  principal_arn = var.principal_arn
}
