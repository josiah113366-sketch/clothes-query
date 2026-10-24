output "role_arns" { value = { for k, role in aws_iam_role.this : k => role.arn } }
output "service_accounts" { value = { for actor in ["submitter", "driver", "executor"] : actor => "${var.service_account_prefix}-${actor}" } }
output "magic_delete_patterns" { value = local.magic_patterns }
