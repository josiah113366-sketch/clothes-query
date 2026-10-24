terraform {
  backend "s3" {
    key          = "clothes-query/dev/spark-access/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
