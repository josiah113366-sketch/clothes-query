output "address" {
  value     = module.rds.address
  sensitive = true
}

output "port" {
  value = module.rds.port
}

output "database_name" {
  value = module.rds.database_name
}

output "master_secret_arn" {
  value     = module.rds.master_secret_arn
  sensitive = true
}
output "logical_replication_enabled" { value = module.rds.logical_replication_enabled }
output "cdc_parameter_group_name" { value = module.rds.cdc_parameter_group_name }
