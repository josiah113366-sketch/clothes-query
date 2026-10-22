output "role_arns" {
  value     = module.gold_b_access.role_arns
  sensitive = true
}
output "workgroups" { value = module.gold_b_access.workgroups }
output "results_locations" {
  value     = module.gold_b_access.results_locations
  sensitive = true
}
output "service_accounts" { value = module.gold_b_access.service_accounts }
output "detection_history_writes_configured" { value = module.gold_b_access.detection_history_writes_configured }
