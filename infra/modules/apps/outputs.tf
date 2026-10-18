output "namespace" { value = kubernetes_namespace_v1.this.metadata[0].name }
output "database_secret_name" { value = var.database_secret_name }
output "workloads_enabled" { value = var.deploy_workloads }
