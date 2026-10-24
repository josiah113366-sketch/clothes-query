output "role_arn" { value = aws_iam_role.dashboard.arn }
output "workgroup_name" { value = aws_athena_workgroup.dashboard.name }
output "results_location" { value = "s3://${local.bucket}/${var.results_prefix}" }
output "service_account" { value = { namespace = var.namespace, name = var.service_account } }
