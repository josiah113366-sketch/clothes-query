# 출력값. 스택 outputs.tf 가 그대로 다시 내보낸다.
# 버킷 이름·계정 ID 는 출력하지 않는다(콘솔 로그·PR 첨부에 남지 않게). 필요하면 SSM 설정 파라미터를 읽는다.

output "workgroup_name" {
  description = "Athena 워크그룹 이름. 쿼리를 이 워크그룹으로 실행한다."
  value       = aws_athena_workgroup.this.name
}

output "database_name" {
  description = "Glue 데이터베이스 이름."
  value       = aws_glue_catalog_database.this.name
}

output "runner_policy_arn" {
  description = "Airflow 역할에 붙일 IAM 정책 ARN(Athena 쿼리, Glue 해당 DB, S3 해당 prefix)."
  value       = aws_iam_policy.athena_runner.arn
}

output "config_parameter_name" {
  description = "스크립트가 읽는 SSM 파라미터 이름."
  value       = aws_ssm_parameter.config.name
}

output "latest_view_name" {
  description = "Gold 가 읽는 Athena 뷰 이름(후기마다 model_version_no 최대 결과). 데이터베이스는 database_name output."
  value       = aws_glue_catalog_table.latest_view.name
}

output "status_view_name" {
  description = "후기 단위 점수 상태 뷰 이름(속성없음/점수있음). 데이터베이스는 database_name output."
  value       = aws_glue_catalog_table.status_view.name
}
