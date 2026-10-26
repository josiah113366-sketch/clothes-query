# Read-only evidence for an acknowledged, unpublished funnel snapshot.
# Keep existing shared/Gold B/Spark/Airflow policies unchanged.
resource "aws_iam_role_policy" "gold_a_demo_evidence" {
  count = var.enable_gold_a_reads ? 1 : 0
  name  = "gold-a-demo-evidence-read-only"
  role  = aws_iam_role.dashboard.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AcknowledgedFunnelEvidence"
      Effect = "Allow"
      Action = ["s3:GetObject"]
      Resource = [
        "${var.bucket_arn}/silver/runtime/clicks/catalog-control/incremental.json",
        "${var.bucket_arn}/gold_a/runtime/funnels/runs/*/manifest.json",
        "${var.bucket_arn}/gold_a/runtime/funnels/completed/*.json",
        "${var.bucket_arn}/pipelines/input-manifests/funnels-incremental/*/inventory.json"
      ]
    }]
  })
}
