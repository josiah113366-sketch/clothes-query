output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  description = "Empty until image_digest is set."
  value       = local.deploy ? aws_ecs_service.this[0].name : ""
}

output "security_group_id" {
  description = "Task SG. Put it in the rds stack database_clients (private input) for the controller data pollution account."
  value       = aws_security_group.task.id
}

output "secret_name" {
  value = aws_secretsmanager_secret.database_url.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}
