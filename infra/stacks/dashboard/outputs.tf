output "repository_url" {
  value     = aws_ecr_repository.dashboard.repository_url
  sensitive = true
}
output "repository_arn" {
  value     = aws_ecr_repository.dashboard.arn
  sensitive = true
}
# GitHub 저장소 변수 DASHBOARD_DEPLOY_ROLE_ARN 에 넣는 값 (terraform output -raw github_actions_role_arn)
output "github_actions_role_arn" {
  value     = aws_iam_role.dashboard_ci.arn
  sensitive = true
}
