output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  description = "image_digest 를 넣기 전에는 빈 값."
  value       = local.deploy ? aws_ecs_service.this[0].name : ""
}

output "security_group_id" {
  description = "태스크 보안 그룹. 데이터 오염용으로 rds 스택 database_clients(비공개 입력)에 넣는다."
  value       = aws_security_group.task.id
}

output "secret_name" {
  value = aws_secretsmanager_secret.database_url.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}
