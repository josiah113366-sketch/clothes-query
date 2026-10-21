# 모듈 출력을 그대로 내보낸다. 버킷 이름·계정 ID 는 출력하지 않는다.
output "role_arn" {
  description = "Processing Job 실행 역할 ARN(PassRole 대상)."
  value       = module.sagemaker_review_score.role_arn
}

output "role_name" {
  value = module.sagemaker_review_score.role_name
}

output "security_group_id" {
  value = module.sagemaker_review_score.security_group_id
}

output "config_parameter_name" {
  description = "스크립트가 읽는 SSM 파라미터 이름."
  value       = module.sagemaker_review_score.config_parameter_name
}

output "image_uri" {
  value = module.sagemaker_review_score.image_uri
}

output "launcher_policy_arn" {
  description = "Airflow 역할에 붙일 IAM 정책 ARN."
  value       = module.sagemaker_review_score.launcher_policy_arn
}
