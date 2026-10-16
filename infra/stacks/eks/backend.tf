terraform {
  backend "s3" {
    key          = "clothes-query/dev/eks/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
