output "vpc_id" { value = aws_vpc.this.id }
output "public_subnet_ids" { value = [for s in aws_subnet.public : s.id] }
output "app_subnet_ids" { value = [for s in aws_subnet.app : s.id] }
output "db_subnet_ids" { value = [for s in aws_subnet.db : s.id] }
output "availability_zones" { value = [for s in values(var.subnets) : s.az] }
output "s3_endpoint_id" { value = aws_vpc_endpoint.s3.id }
output "s3_endpoint_actions" {
  value = toset(concat(
    ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"],
    tolist(var.additional_s3_endpoint_actions)
  ))
}
