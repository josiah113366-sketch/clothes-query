terraform {
  backend "s3" {
    key          = "clothes-query/dev/workload-access/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
