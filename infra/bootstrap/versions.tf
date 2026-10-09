terraform {
  # use_lockfile(S3 네이티브 락)을 쓰는 다른 스택과 맞추기 위해 1.10 이상
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
