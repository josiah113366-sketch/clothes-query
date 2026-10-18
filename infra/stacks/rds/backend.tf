terraform {
  backend "s3" {
    key          = "clothes-query/dev/rds/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
