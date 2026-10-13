module "network" {
  source   = "../../modules/network"
  name     = "clothes-query-dev-network"
  region   = var.aws_region
  vpc_cidr = var.vpc_cidr
  subnets  = var.subnets
}
