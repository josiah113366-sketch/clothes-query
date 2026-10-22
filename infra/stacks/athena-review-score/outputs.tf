# 모듈 출력을 그대로 내보낸다. 버킷 이름·계정 ID 는 출력하지 않는다.
output "workgroup_name" {
  description = "Athena 워크그룹 이름."
  value       = module.athena_review_score.workgroup_name
}

output "database_name" {
  description = "Glue 데이터베이스 이름."
  value       = module.athena_review_score.database_name
}

output "runner_policy_arn" {
  description = "Airflow 역할에 붙일 IAM 정책 ARN."
  value       = module.athena_review_score.runner_policy_arn
}

output "config_parameter_name" {
  description = "스크립트가 읽는 SSM 파라미터 이름."
  value       = module.athena_review_score.config_parameter_name
}
