output "repository_url" {
  value     = aws_ecr_repository.dashboard.repository_url
  sensitive = true
}
output "repository_arn" {
  value     = aws_ecr_repository.dashboard.arn
  sensitive = true
}
