resource "aws_ecr_repository" "this" {
  for_each = toset(concat(
    ["web", "was"], var.enable_connect_repository ? ["connect"] : [],
    var.enable_spark_repositories ? ["spark-base", "silver-gold-a"] : [],
    var.enable_gold_b_repository ? ["gold-b"] : []
  ))
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_user_policy" "spark_image_push" {
  for_each = var.enable_spark_repositories ? var.spark_publisher_user_arns : toset([])
  name     = "${var.name}-spark-image-push"
  user     = element(reverse(split("/", each.value)), 0)
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SelectedSparkRepositories"
        Effect   = "Allow"
        Resource = [for key in ["spark-base", "silver-gold-a"] : aws_ecr_repository.this[key].arn]
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"
        ]
      },
      # Registry token retrieval has no repository-scoped resource ARN.
      { Sid = "RegistryAuthentication", Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" }
    ]
  })
  lifecycle {
    precondition {
      condition     = split(":", each.value)[4] == data.aws_caller_identity.current.account_id
      error_message = "The Spark publisher must be an IAM user in the deployed AWS account."
    }
  }
}
