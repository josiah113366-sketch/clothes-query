terraform {
  backend "s3" {
    key          = "clothes-query/dev/gold-b-access/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
