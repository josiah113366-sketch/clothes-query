terraform {
  backend "s3" {
    key          = "clothes-query/dev/infrastructure-alerts/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
