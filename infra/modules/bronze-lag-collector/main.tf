data "aws_caller_identity" "current" {}

resource "aws_ecr_repository" "this" {
  name                 = "${var.name}/gold-b-lag-collector"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

resource "aws_iam_role" "this" {
  name = "${var.name}-gold-b-lag-collector"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"]
      Condition = { StringEquals = {
        "aws:RequestTag/eks-cluster-arn"            = "arn:aws:eks:ap-northeast-1:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
        "aws:RequestTag/kubernetes-namespace"       = var.namespace
        "aws:RequestTag/kubernetes-service-account" = "gold-b-lag-collector"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "this" {
  name = "write-bronze-lag-snapshots-only"
  role = aws_iam_role.this.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${var.bucket_arn}/gold_b/bronze_lag_snapshots/*"] },
      { Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = [var.bucket_arn] }
    ]
  })
}

resource "aws_eks_pod_identity_association" "this" {
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = "gold-b-lag-collector"
  role_arn        = aws_iam_role.this.arn
  depends_on      = [aws_iam_role_policy.this]
}
