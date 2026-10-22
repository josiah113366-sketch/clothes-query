terraform {
  backend "s3" {
    key          = "clothes-query/dev/agent-development-access/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
