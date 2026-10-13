terraform {
  backend "s3" {
    key          = "clothes-query/dev/ecr/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
