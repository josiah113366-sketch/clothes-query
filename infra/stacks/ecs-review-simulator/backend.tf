terraform {
  backend "s3" {
    key          = "clothes-query/dev/ecs-review-simulator/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
