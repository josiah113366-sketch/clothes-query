terraform {
  backend "s3" {
    key          = "clothes-query/dev/bronze-lag-collector/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
