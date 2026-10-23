locals {
  actors         = var.enabled ? toset(["driver", "executor"]) : toset([])
  object_actions = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
  required_actions = concat(local.object_actions, ["s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation"],
  var.allow_bucket_multipart_listing ? ["s3:ListBucketMultipartUploads"] : [])
  # Only job working objects under a run's dataset; never finished Parquet/manifests.
  magic_patterns = [for p in sort(tolist(var.output_prefixes)) : "${p}runs/*/*/__magic_job-*/*"]
}
resource "aws_iam_role" "this" {
  for_each = local.actors
  name     = "clothes-query-dev-${var.service_account_prefix}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"]
      Condition = { StringEquals = {
        "aws:RequestTag/kubernetes-namespace"       = var.namespace
        "aws:RequestTag/kubernetes-service-account" = "${var.service_account_prefix}-${each.key}"
      } }
    }]
  })
  lifecycle {
    precondition {
      condition     = alltrue([for action in local.required_actions : contains(var.s3_endpoint_actions, action)])
      error_message = "Update the network endpoint transport permissions before enabling these Spark roles."
    }
  }
}
resource "aws_iam_role_policy" "s3" {
  for_each = local.actors
  name     = "trade-magic-committer"
  role     = aws_iam_role.this[each.key].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Sid = "InputRead", Effect = "Allow", Action = ["s3:GetObject"], Resource = [for p in sort(tolist(var.read_prefixes)) : "${var.bucket_arn}/${p}*"] },
      { Sid = "OutputAndMultipart", Effect = "Allow", Action = local.object_actions, Resource = [for p in sort(tolist(var.output_prefixes)) : "${var.bucket_arn}/${p}*"] },
      { Sid = "MagicWorkingObjectsOnly", Effect = "Allow", Action = ["s3:DeleteObject"], Resource = [for p in local.magic_patterns : "${var.bucket_arn}/${p}"] },
      { Sid = "SelectedPrefixListing", Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for p in sort(tolist(setunion(var.read_prefixes, var.output_prefixes))) : "${p}*"] } } },
      { Sid = "BucketLocation", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = [var.bucket_arn] }
      ], var.allow_bucket_multipart_listing ? [
      { Sid = "OptionalMultipartMetadataListing", Effect = "Allow", Action = ["s3:ListBucketMultipartUploads"], Resource = [var.bucket_arn] }
    ] : [])
  })
}
resource "aws_eks_pod_identity_association" "this" {
  for_each        = local.actors
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = "${var.service_account_prefix}-${each.key}"
  role_arn        = aws_iam_role.this[each.key].arn
  depends_on      = [aws_iam_role_policy.s3]
}
