# All providers are mocked. These plans never authenticate to AWS or create resources.
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-northeast-1a", "ap-northeast-1c"] }
  }
}
run "network_ha" {
  command = plan
  module { source = "../modules/network" }
  override_resource {
    target          = aws_route_table.app["a"]
    values          = { id = "rtb-test-a" }
    override_during = plan
  }
  override_resource {
    target          = aws_route_table.app["c"]
    values          = { id = "rtb-test-c" }
    override_during = plan
  }
  variables {
    name     = "test-network"
    region   = "ap-northeast-1"
    vpc_cidr = "10.70.0.0/16"
    subnets = {
      a = { az = "ap-northeast-1a", public_cidr = "10.70.0.0/24", app_cidr = "10.70.16.0/20", db_cidr = "10.70.64.0/24" }
      c = { az = "ap-northeast-1c", public_cidr = "10.70.1.0/24", app_cidr = "10.70.32.0/20", db_cidr = "10.70.65.0/24" }
    }
  }
  assert {
    condition     = length(aws_nat_gateway.this) == 2 && length(aws_route_table.app) == 2
    error_message = "Each AZ must have its own NAT and app route table."
  }
  assert {
    condition     = aws_vpc_endpoint.s3.vpc_endpoint_type == "Gateway" && length(aws_vpc_endpoint.s3.route_table_ids) == 2
    error_message = "Both app route tables must use the S3 gateway endpoint."
  }
  assert {
    condition     = alltrue([for s in aws_subnet.app : !s.map_public_ip_on_launch]) && alltrue([for s in aws_subnet.db : !s.map_public_ip_on_launch])
    error_message = "App and DB subnets must not assign public IPv4 addresses."
  }
  assert {
    condition     = output.s3_endpoint_actions == toset(["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"])
    error_message = "Existing network defaults must not broaden endpoint transport permissions."
  }
}
run "reject_overlapping_subnets" {
  command = plan
  module { source = "../modules/network" }
  variables {
    name     = "test-overlap"
    region   = "ap-northeast-1"
    vpc_cidr = "10.70.0.0/16"
    subnets = {
      a = { az = "ap-northeast-1a", public_cidr = "10.70.0.0/24", app_cidr = "10.70.0.0/20", db_cidr = "10.70.64.0/24" }
      c = { az = "ap-northeast-1c", public_cidr = "10.70.1.0/24", app_cidr = "10.70.32.0/20", db_cidr = "10.70.65.0/24" }
    }
  }
  expect_failures = [aws_vpc.this]
}
run "reject_wrong_region_az" {
  command = plan
  module { source = "../modules/network" }
  variables {
    name     = "test-region"
    region   = "ap-northeast-1"
    vpc_cidr = "10.70.0.0/16"
    subnets = {
      a = { az = "us-east-2a", public_cidr = "10.70.0.0/24", app_cidr = "10.70.16.0/20", db_cidr = "10.70.64.0/24" }
      c = { az = "us-east-2c", public_cidr = "10.70.1.0/24", app_cidr = "10.70.32.0/20", db_cidr = "10.70.65.0/24" }
    }
  }
  expect_failures = [aws_vpc.this]
}
run "rds_ha_and_preservation" {
  command = plan
  module { source = "../modules/rds" }
  variables {
    name                       = "test-rds"
    vpc_id                     = "vpc-test"
    db_subnet_ids              = ["subnet-test-a", "subnet-test-c"]
    workload_security_group_id = "sg-test"
    engine_version             = "16"
    instance_class             = "db.m6g.large"
    allocated_storage          = 20
    max_allocated_storage      = 100
  }
  assert {
    condition     = aws_db_instance.this.multi_az && !aws_db_instance.this.publicly_accessible && aws_db_instance.this.storage_encrypted
    error_message = "RDS must be private, encrypted and Multi-AZ."
  }
  assert {
    condition     = aws_db_instance.this.deletion_protection && !aws_db_instance.this.skip_final_snapshot && aws_db_instance.this.backup_retention_period >= 7
    error_message = "RDS deletion protection and backups must be preserved."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.postgres.from_port == 5432 && aws_vpc_security_group_ingress_rule.postgres.referenced_security_group_id == "sg-test"
    error_message = "PostgreSQL must only admit the workload security group."
  }
}
run "storage_protection" {
  command = plan
  module { source = "../modules/storage" }
  variables { bucket_name = "clothes-query-test-only-not-created" }
  assert {
    condition     = !aws_s3_bucket.this.force_destroy && aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled"
    error_message = "Data deletion protection and versioning are required."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.this.block_public_policy && aws_s3_bucket_public_access_block.this.restrict_public_buckets
    error_message = "The data bucket must remain private."
  }
}
