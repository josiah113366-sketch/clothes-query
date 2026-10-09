output "tfstate_bucket_name" {
  description = "state 버킷 이름. 각 스택 backend.tf의 bucket에 그대로 적는다"
  value       = aws_s3_bucket.tfstate.bucket
}

output "tfstate_bucket_arn" {
  description = "state 버킷 ARN"
  value       = aws_s3_bucket.tfstate.arn
}

output "tfstate_bucket_region" {
  description = "state 버킷 리전"
  value       = aws_s3_bucket.tfstate.region
}
