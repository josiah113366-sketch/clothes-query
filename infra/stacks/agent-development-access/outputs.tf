output "developer_role_arn" {
  value     = module.agent_development_access.developer_role_arn
  sensitive = true
}
output "repository_urls" {
  value     = module.agent_development_access.repository_urls
  sensitive = true
}
