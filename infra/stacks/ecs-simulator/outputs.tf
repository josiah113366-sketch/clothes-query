output "ecr_repository_url" { value = module.ecs_simulator.ecr_repository_url }
output "cluster_name" { value = module.ecs_simulator.cluster_name }
output "service_name" { value = module.ecs_simulator.service_name }
output "security_group_id" { value = module.ecs_simulator.security_group_id }
output "secret_name" { value = module.ecs_simulator.secret_name }
output "log_group_name" { value = module.ecs_simulator.log_group_name }
