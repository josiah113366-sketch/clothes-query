output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnet_ids" {
  value = module.network.public_subnet_ids
}

output "app_subnet_ids" {
  value = module.network.app_subnet_ids
}

output "db_subnet_ids" {
  value = module.network.db_subnet_ids
}

output "availability_zones" {
  value = module.network.availability_zones
}

output "s3_endpoint_id" {
  value = module.network.s3_endpoint_id
}
output "s3_endpoint_actions" { value = module.network.s3_endpoint_actions }
