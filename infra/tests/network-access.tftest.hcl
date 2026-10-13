mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-northeast-1a", "ap-northeast-1c"] }
  }
}
variables {
  name     = "test-network-access"
  region   = "ap-northeast-1"
  vpc_cidr = "10.70.0.0/16"
  subnets = {
    a = { az = "ap-northeast-1a", public_cidr = "10.70.0.0/24", app_cidr = "10.70.16.0/20", db_cidr = "10.70.64.0/24" }
    c = { az = "ap-northeast-1c", public_cidr = "10.70.1.0/24", app_cidr = "10.70.32.0/20", db_cidr = "10.70.65.0/24" }
  }
}
run "explicit_optional_transport_actions" {
  command = plan
  module { source = "../modules/network" }
  variables { additional_s3_endpoint_actions = ["s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"] }
  assert {
    condition = (
      output.s3_endpoint_actions == toset(["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]) &&
      toset(jsondecode(aws_vpc_endpoint.s3.policy).Statement[0].Action) == output.s3_endpoint_actions
    )
    error_message = "The network output and endpoint policy must agree on explicit optional transport actions."
  }
}
run "reject_wildcard_transport_action" {
  command = plan
  module { source = "../modules/network" }
  variables { additional_s3_endpoint_actions = ["s3:*"] }
  expect_failures = [var.additional_s3_endpoint_actions]
}
