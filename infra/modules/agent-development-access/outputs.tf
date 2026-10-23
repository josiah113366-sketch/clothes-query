output "developer_role_arn" { value = aws_iam_role.developer.arn }
output "repository_urls" { value = { for name, repo in aws_ecr_repository.agent : name => repo.repository_url } }
output "repository_arns" { value = { for name, repo in aws_ecr_repository.agent : name => repo.arn } }
