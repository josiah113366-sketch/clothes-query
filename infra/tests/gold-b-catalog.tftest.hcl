mock_provider "aws" {}
run "catalog_only_points_to_existing_gold_prefix" {
  command = plan
  module { source = "../modules/gold-b-catalog" }
  variables { bucket_name = "test-existing-data-bucket" }
  assert {
    condition     = aws_glue_catalog_database.gold_b.name == "gold_b" && aws_glue_catalog_database.gold_b.location_uri == "s3://test-existing-data-bucket/gold_b/"
    error_message = "Register only gold_b in the existing data bucket."
  }
}
run "reject_uri_instead_of_bucket_name" {
  command = plan
  module { source = "../modules/gold-b-catalog" }
  variables { bucket_name = "s3://other-bucket/prefix/" }
  expect_failures = [var.bucket_name]
}
