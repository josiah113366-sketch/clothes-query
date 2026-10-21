# 출력값. 스택 outputs.tf 가 그대로 다시 내보낸다.
# 버킷 이름·계정 ID 는 출력하지 않는다(콘솔 로그·PR 첨부에 남지 않게). 필요하면 SSM 설정 파라미터를 읽는다.

output "role_arn" {
  description = "Processing Job 실행 역할 ARN. Job 을 만드는 사람/스크립트는 이 역할에 iam:PassRole 권한이 필요하다."
  value       = aws_iam_role.processing.arn
}

output "role_name" {
  description = "Processing Job 실행 역할 이름."
  value       = aws_iam_role.processing.name
}

output "security_group_id" {
  description = "Job 용 보안 그룹 ID. use_vpc=false 면 null."
  value       = local.vpc_enabled ? aws_security_group.processing[0].id : null
}

output "config_parameter_name" {
  description = "스크립트가 읽는 SSM 파라미터 이름."
  value       = aws_ssm_parameter.config.name
}

output "image_uri" {
  description = "사용하는 DLC 이미지 URI(공개 이미지라 민감하지 않음)."
  value       = local.image_uri
}

output "launcher_policy_arn" {
  description = "Airflow 역할에 붙일 IAM 정책 ARN(Job 생성/조회/중지, PassRole, SSM 설정 읽기)."
  value       = aws_iam_policy.launcher.arn
}
