module "storage" {
  source      = "../../modules/storage"
  bucket_name = var.bucket_name
}
