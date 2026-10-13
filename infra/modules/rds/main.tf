resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.db_subnet_ids
}
resource "aws_security_group" "this" {
  name        = var.name
  description = "PostgreSQL from the EKS Auto Mode workload security group"
  vpc_id      = var.vpc_id
}
resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = var.workload_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
resource "aws_db_parameter_group" "cdc" {
  count       = var.logical_replication == null ? 0 : 1
  name_prefix = "${var.name}-cdc-"
  family      = "postgres${split(".", var.engine_version)[0]}"
  description = "Opt-in PostgreSQL CDC settings with explicit replication budgets"

  parameter {
    name         = "rds.logical_replication"
    value        = "1"
    apply_method = "pending-reboot"
  }
  dynamic "parameter" {
    for_each = var.logical_replication == null ? {} : {
      max_replication_slots  = tostring(var.logical_replication.max_replication_slots)
      max_wal_senders        = tostring(var.logical_replication.max_wal_senders)
      max_slot_wal_keep_size = tostring(var.logical_replication.max_slot_wal_keep_size_mb)
    }
    content {
      name         = parameter.key
      value        = parameter.value
      apply_method = "pending-reboot"
    }
  }
  lifecycle { create_before_destroy = true }
}
resource "aws_db_instance" "this" {
  identifier                  = var.name
  engine                      = "postgres"
  engine_version              = var.engine_version
  instance_class              = var.instance_class
  allocated_storage           = var.allocated_storage
  max_allocated_storage       = var.max_allocated_storage
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = var.database_name
  username                    = "dbadmin"
  manage_master_user_password = true
  port                        = 5432
  multi_az                    = true
  publicly_accessible         = false
  db_subnet_group_name        = aws_db_subnet_group.this.name
  parameter_group_name        = var.logical_replication == null ? null : aws_db_parameter_group.cdc[0].name
  vpc_security_group_ids      = [aws_security_group.this.id]
  backup_retention_period     = 7
  copy_tags_to_snapshot       = true
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${var.name}-final"
  apply_immediately           = false
  auto_minor_version_upgrade  = true
  lifecycle { prevent_destroy = true }
}
