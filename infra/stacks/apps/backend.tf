terraform {
  backend "s3" {
    key          = "clothes-query/dev/apps/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
