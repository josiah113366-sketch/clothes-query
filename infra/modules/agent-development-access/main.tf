data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_ecr_repository" "agent" {
  for_each             = var.repository_names
  name                 = "${var.name}/${each.value}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

resource "aws_iam_role" "developer" {
  name = "${var.name}-agent-developer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = sort(tolist(var.trusted_principal_arns)) }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "developer" {
  name = "describe-cluster-and-publish-agent-images"
  role = aws_iam_role.developer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = ["arn:${data.aws_partition.current.partition}:eks:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"]
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages", "ecr:DescribeRepositories", "ecr:ListImages"]
        Resource = [for repo in aws_ecr_repository.agent : repo.arn]
      }
    ]
  })
}

resource "aws_eks_access_entry" "developer" {
  cluster_name      = var.cluster_name
  principal_arn     = aws_iam_role.developer.arn
  type              = "STANDARD"
  kubernetes_groups = ["clothes-query:agent-developers"]
}
