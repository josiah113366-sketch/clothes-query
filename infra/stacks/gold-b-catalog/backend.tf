terraform {
  backend "s3" {
    key          = "clothes-query/dev/gold-b-catalog/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
