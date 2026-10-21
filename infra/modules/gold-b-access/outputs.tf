output "role_arns" {
  value     = { for k, r in aws_iam_role.this : k => r.arn }
  sensitive = true
}
output "workgroups" { value = { for k, w in aws_athena_workgroup.this : k => w.name } }
output "results_locations" {
  value     = { for k, w in aws_athena_workgroup.this : k => w.configuration[0].result_configuration[0].output_location }
  sensitive = true
}
output "service_accounts" { value = { for k, sa in local.workloads : k => { namespace = var.namespace, name = sa } } }
output "detection_history_writes_configured" { value = length(var.detection_write_prefixes) > 0 }
output "investigation_database" { value = var.enable_investigation_catalog ? aws_glue_catalog_database.investigation[0].name : null }
