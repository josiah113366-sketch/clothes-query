module "ecr" {
  source                    = "../../modules/ecr"
  name                      = "clothes-query-dev"
  enable_connect_repository = var.enable_connect_repository
  enable_spark_repositories = var.enable_spark_repositories
  spark_publisher_user_arns = var.spark_publisher_user_arns
}
