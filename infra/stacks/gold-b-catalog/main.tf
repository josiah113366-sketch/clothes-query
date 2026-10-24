data "terraform_remote_state" "storage" {
  backend = "s3"
  config  = { bucket = var.state_bucket, region = "ap-northeast-1", key = "clothes-query/dev/storage/terraform.tfstate" }
}
module "gold_b_catalog" {
  source      = "../../modules/gold-b-catalog"
  bucket_name = trimprefix(data.terraform_remote_state.storage.outputs.bucket_arn, "arn:aws:s3:::")
}
