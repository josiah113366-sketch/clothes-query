terraform {
  backend "s3" {
    key          = "clothes-query/dev/dashboard/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
