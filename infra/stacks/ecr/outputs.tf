output "repository_urls" {
  value     = module.ecr.repository_urls
  sensitive = true
}
output "repository_arns" {
  value     = module.ecr.repository_arns
  sensitive = true
}
output "connect_publisher_policy" {
  value     = module.ecr.connect_publisher_policy
  sensitive = true
}
