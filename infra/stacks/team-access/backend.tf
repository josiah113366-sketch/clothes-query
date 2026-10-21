terraform {
  backend "s3" {
    key          = "clothes-query/dev/team-access/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
