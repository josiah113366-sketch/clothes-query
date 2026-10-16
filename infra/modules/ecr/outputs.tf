output "repository_urls" {
  value     = { for k, r in aws_ecr_repository.this : k => r.repository_url }
  sensitive = true
}
output "repository_arns" {
  value     = { for k, r in aws_ecr_repository.this : k => r.arn }
  sensitive = true
}
output "connect_publisher_policy" {
  description = "Policy document for the separately selected publishing identity; does not create/attach IAM permissions."
  sensitive   = true
  value = var.enable_connect_repository ? jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ConnectImagePush"
        Effect   = "Allow"
        Resource = aws_ecr_repository.this["connect"].arn
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:PutImage"
        ]
      },
      {
        Sid      = "RegistryAuthentication"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      }
    ]
  }) : null
}
