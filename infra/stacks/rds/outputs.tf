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
