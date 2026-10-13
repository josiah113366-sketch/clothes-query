output "namespace" {
  value = module.apps.namespace
}

output "database_secret_name" {
  value = module.apps.database_secret_name
}

output "workloads_enabled" {
  value = module.apps.workloads_enabled
}
