output "address" {
  value     = aws_db_instance.this.address
  sensitive = true
}
output "port" { value = aws_db_instance.this.port }
output "database_name" { value = aws_db_instance.this.db_name }
output "master_secret_arn" {
  value     = aws_db_instance.this.master_user_secret[0].secret_arn
  sensitive = true
}
output "logical_replication_enabled" { value = var.logical_replication != null }
output "cdc_parameter_group_name" { value = try(aws_db_parameter_group.cdc[0].name, null) }
