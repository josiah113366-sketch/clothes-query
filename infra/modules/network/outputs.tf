output "vpc_id" { value = aws_vpc.this.id }
output "public_subnet_ids" { value = [for s in aws_subnet.public : s.id] }
output "app_subnet_ids" { value = [for s in aws_subnet.app : s.id] }
output "db_subnet_ids" { value = [for s in aws_subnet.db : s.id] }
output "availability_zones" { value = [for s in values(var.subnets) : s.az] }
output "s3_endpoint_id" { value = aws_vpc_endpoint.s3.id }

output "workload_az" { value = var.workload_az }
output "workload_subnet_ids" { value = [for k, s in aws_subnet.app : s.id if var.subnets[k].az == var.workload_az] }
