resource "aws_iam_role" "this" {
  for_each = var.bindings
  name     = "${var.name}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = {
        StringEquals = {
          "aws:RequestTag/kubernetes-namespace"       = each.value.namespace
          "aws:RequestTag/kubernetes-service-account" = each.value.service_account
        }
      }
    }]
  })
}
resource "aws_iam_role_policy" "s3" {
  for_each = var.bindings
  name     = "scoped-data-access"
  role     = aws_iam_role.this[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [for prefix, actions in each.value.s3_access : {
        Effect   = "Allow"
        Action   = sort(tolist(actions))
        Resource = ["${var.bucket_arn}/${prefix}*"]
      }],
      [for path in sort(tolist(each.value.s3_directory_reads)) : {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${var.bucket_arn}/${path}"]
      }],
      [
        {
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = [var.bucket_arn]
          Condition = {
            StringLike = { "s3:prefix" = concat([for prefix in sort(keys(each.value.s3_access)) : "${prefix}*"], sort(tolist(each.value.s3_directory_reads))) }
          }
        },
        { Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = [var.bucket_arn] }
      ]
    )
  })
}
resource "aws_eks_pod_identity_association" "this" {
  for_each        = var.bindings
  cluster_name    = var.cluster_name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.this[each.key].arn
  depends_on      = [aws_iam_role_policy.s3]
}
