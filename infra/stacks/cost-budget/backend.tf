terraform {
  backend "s3" {
    key          = "clothes-query/dev/cost-budget/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
