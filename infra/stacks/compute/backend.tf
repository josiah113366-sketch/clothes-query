terraform {
  backend "s3" {
    key          = "clothes-query/dev/compute/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
