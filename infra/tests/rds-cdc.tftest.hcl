mock_provider "aws" {}

# All numbers below are test fixtures, not measured or approved deployment sizing.
variables {
  name                       = "test-rds"
  vpc_id                     = "vpc-test"
  db_subnet_ids              = ["subnet-test-a", "subnet-test-c"]
  workload_security_group_id = "sg-test"
  availability_zone          = "ap-northeast-1a"
  engine_version             = "16.15"
  instance_class             = "db.m6g.large"
  allocated_storage          = 20
  max_allocated_storage      = 100
}

run "cdc_disabled_by_default" {
  command = plan
  module { source = "../modules/rds" }
  assert {
    condition     = length(aws_db_parameter_group.cdc) == 0 && !output.logical_replication_enabled
    error_message = "Existing RDS inputs must not opt into CDC or create a custom parameter group."
  }
  assert {
    condition     = !aws_db_instance.this.multi_az && aws_db_instance.this.availability_zone == "ap-northeast-1a" && aws_db_instance.this.deletion_protection && !aws_db_instance.this.apply_immediately
    error_message = "CDC preparation must preserve the single workload AZ, deletion protection and deferred DB changes."
  }
}

run "explicit_cdc_parameters_are_attached" {
  command = plan
  module { source = "../modules/rds" }
  variables {
    logical_replication = {
      max_replication_slots     = 4
      max_wal_senders           = 6
      max_slot_wal_keep_size_mb = 1024
    }
  }
  override_resource {
    target          = aws_db_parameter_group.cdc[0]
    values          = { name = "test-rds-cdc-parameters" }
    override_during = plan
  }
  assert {
    condition = (
      aws_db_parameter_group.cdc[0].family == "postgres16" &&
      aws_db_instance.this.parameter_group_name == "test-rds-cdc-parameters" &&
      output.logical_replication_enabled && !aws_db_instance.this.apply_immediately
    )
    error_message = "CDC must use the engine-major family and attach its group without forcing immediate DB changes."
  }
  assert {
    condition = alltrue([for name, expected in {
      "rds.logical_replication" = "1"
      max_replication_slots     = "4"
      max_wal_senders           = "6"
      max_slot_wal_keep_size    = "1024"
      } : lookup({ for p in aws_db_parameter_group.cdc[0].parameter : p.name => p.value }, name, null) == expected
    ]) && alltrue([for p in aws_db_parameter_group.cdc[0].parameter : p.apply_method == "pending-reboot"])
    error_message = "Explicit slot/sender/WAL budgets and logical decoding must be prepared for a reviewed reboot."
  }
}

run "reject_unlimited_wal_budget" {
  command = plan
  module { source = "../modules/rds" }
  variables {
    logical_replication = {
      max_replication_slots     = 4
      max_wal_senders           = 6
      max_slot_wal_keep_size_mb = -1
    }
  }
  expect_failures = [var.logical_replication]
}

run "reject_placeholder_engine_when_cdc_enabled" {
  command = plan
  module { source = "../modules/rds" }
  variables {
    engine_version = "REPLACE_WITH_APPROVED_VERSION"
    logical_replication = {
      max_replication_slots     = 4
      max_wal_senders           = 6
      max_slot_wal_keep_size_mb = 1024
    }
  }
  expect_failures = [var.logical_replication]
}
