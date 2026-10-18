terraform {
  backend "s3" {
    key          = "clothes-query/dev/network/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
