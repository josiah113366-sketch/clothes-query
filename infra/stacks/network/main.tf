module "network" {
  source                         = "../../modules/network"
  name                           = "clothes-query-dev-network"
  region                         = var.aws_region
  vpc_cidr                       = var.vpc_cidr
  subnets                        = var.subnets
  additional_s3_endpoint_actions = var.additional_s3_endpoint_actions
}
