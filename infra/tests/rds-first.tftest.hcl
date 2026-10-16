# RDS-first deployment retains subnet structure without paid NAT/EKS resources.
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-northeast-1a", "ap-northeast-1c"] }
  }
}
run "network_without_nat" {
  command = plan
  module { source = "../modules/network" }
  variables {
    name                = "test-rds-first"
    region              = "ap-northeast-1"
    enable_nat_gateways = false
    single_nat_gateway  = true
    vpc_cidr            = "10.70.0.0/16"
    subnets = {
      a = { az = "ap-northeast-1a", public_cidr = "10.70.0.0/24", app_cidr = "10.70.16.0/20", db_cidr = "10.70.64.0/24" }
      c = { az = "ap-northeast-1c", public_cidr = "10.70.1.0/24", app_cidr = "10.70.32.0/20", db_cidr = "10.70.65.0/24" }
    }
  }
  assert {
    condition     = length(aws_nat_gateway.this) == 0 && length(aws_eip.nat) == 0 && length(aws_subnet.db) == 2
    error_message = "RDS-first networking must keep DB subnets without NAT/EIP resources."
  }
  assert {
    condition     = alltrue([for s in aws_subnet.app : !s.map_public_ip_on_launch]) && alltrue([for s in aws_subnet.db : !s.map_public_ip_on_launch]) && aws_vpc_endpoint.s3.vpc_endpoint_type == "Gateway"
    error_message = "App/DB subnets must stay private and retain the S3 gateway endpoint."
  }
}
run "private_rds_without_clients" {
  command = plan
  module { source = "../modules/rds" }
  variables {
    name                  = "test-rds-first"
    vpc_id                = "vpc-test"
    db_subnet_ids         = ["subnet-test-a", "subnet-test-c"]
    availability_zone     = "ap-northeast-1a"
    engine_version        = "16.15"
    instance_class        = "db.t4g.small"
    allocated_storage     = 20
    max_allocated_storage = 100
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.postgres) == 0 && length(aws_vpc_security_group_ingress_rule.clients) == 0 && !aws_db_instance.this.publicly_accessible
    error_message = "RDS must remain private with no clients admitted until explicitly configured."
  }
}
run "explicit_generator_client" {
  command = plan
  module { source = "../modules/rds" }
  variables {
    name                  = "test-rds-first"
    vpc_id                = "vpc-test"
    db_subnet_ids         = ["subnet-test-a", "subnet-test-c"]
    availability_zone     = "ap-northeast-1a"
    engine_version        = "16.15"
    instance_class        = "db.t4g.small"
    allocated_storage     = 20
    max_allocated_storage = 100
    database_clients      = { generator = "sg-0123456789abcdef0" }
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.postgres) == 0 && length(aws_vpc_security_group_ingress_rule.clients) == 1 && aws_vpc_security_group_ingress_rule.clients["generator"].referenced_security_group_id == "sg-0123456789abcdef0" && aws_vpc_security_group_ingress_rule.clients["generator"].from_port == 5432 && aws_vpc_security_group_ingress_rule.clients["generator"].to_port == 5432
    error_message = "Only the explicit generator security group may access PostgreSQL."
  }
}
