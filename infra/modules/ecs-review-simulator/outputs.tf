output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "task_family" {
  value = local.task_family
}

output "security_group_id" {
  description = "Task SG. Give to the RDS owner when the simulator needs DB access (database_clients)."
  value       = aws_security_group.task.id
}

output "secret_name" {
  value = aws_secretsmanager_secret.bedrock_api_key.name
}

output "orders_db_secret_name" {
  description = "RDS 접속 주소 secret 이름 (값은 deploy/secret.py --orders-db)"
  value       = aws_secretsmanager_secret.orders_database_url.name
}

output "schedule_name" {
  value = aws_scheduler_schedule.daily.name
}

output "config_parameter_name" {
  value = aws_ssm_parameter.config.name
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.this.dashboard_name
}
