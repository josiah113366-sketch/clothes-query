output "role_arns" {
  value     = { for key, role in aws_iam_role.this : key => role.arn }
  sensitive = true
}
output "service_accounts" {
  value = { for key, binding in var.bindings : key => {
    namespace       = binding.namespace
    service_account = binding.service_account
  } }
}
