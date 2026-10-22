# Terraform / provider 버전. use_lockfile 때문에 1.10 이상이 필요하다. .terraform.lock.hcl 은 커밋한다.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
