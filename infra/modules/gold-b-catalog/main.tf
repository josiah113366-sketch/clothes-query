resource "aws_glue_catalog_database" "gold_b" {
  name         = "gold_b"
  description  = "Gold B ledgers and views; table DDL is owned by pipelines/gold_b"
  location_uri = "s3://${var.bucket_name}/gold_b/"

  lifecycle {
    prevent_destroy = true
  }
}
