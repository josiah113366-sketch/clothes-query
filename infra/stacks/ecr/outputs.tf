output "repository_urls" {
  value     = module.ecr.repository_urls
  sensitive = true
}
