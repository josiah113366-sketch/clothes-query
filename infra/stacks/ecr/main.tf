module "ecr" {
  source                    = "../../modules/ecr"
  name                      = "clothes-query-dev"
  enable_connect_repository = var.enable_connect_repository
}
