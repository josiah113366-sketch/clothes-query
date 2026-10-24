terraform {
  backend "s3" {
    key          = "clothes-query/dev/dashboard-access/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
