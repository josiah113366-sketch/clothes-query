terraform {
  backend "s3" {
    key          = "clothes-query/dev/storage/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
