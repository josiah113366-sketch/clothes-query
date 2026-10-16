data "aws_availability_zones" "available" { state = "available" }

# Compare inclusive IPv4 intervals to reject overlaps before AWS creates subnets.
locals {
  subnet_cidrs = flatten([for s in values(var.subnets) : [s.public_cidr, s.app_cidr, s.db_cidr]])
  subnet_ranges = [for c in local.subnet_cidrs : {
    first = sum([for i, octet in split(".", cidrhost(c, 0)) : tonumber(octet) * pow(256, 3 - i)])
    last  = sum([for i, octet in split(".", cidrhost(c, -1)) : tonumber(octet) * pow(256, 3 - i)])
  }]
  vpc_first = sum([for i, octet in split(".", cidrhost(var.vpc_cidr, 0)) : tonumber(octet) * pow(256, 3 - i)])
  vpc_last  = sum([for i, octet in split(".", cidrhost(var.vpc_cidr, -1)) : tonumber(octet) * pow(256, 3 - i)])
}
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
  lifecycle {
    precondition {
      condition     = alltrue([for r in local.subnet_ranges : r.first >= local.vpc_first && r.last <= local.vpc_last])
      error_message = "All subnets must be contained in the VPC CIDR."
    }
    precondition {
      condition     = alltrue(flatten([for i, a in local.subnet_ranges : [for j, b in local.subnet_ranges : i == j || a.last < b.first || b.last < a.first]]))
      error_message = "Subnet CIDRs must not overlap."
    }
    precondition {
      condition     = alltrue([for s in values(var.subnets) : contains(data.aws_availability_zones.available.names, s.az)])
      error_message = "Every selected AZ must be available in the provider region."
    }
  }
}
resource "aws_internet_gateway" "this" { vpc_id = aws_vpc.this.id }
resource "aws_subnet" "public" {
  for_each                = var.subnets
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.value.az
  cidr_block              = each.value.public_cidr
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-public-${each.key}", "kubernetes.io/role/elb" = "1" }
}
resource "aws_subnet" "app" {
  for_each                = var.subnets
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.value.az
  cidr_block              = each.value.app_cidr
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-app-${each.key}", "kubernetes.io/role/internal-elb" = "1" }
}
resource "aws_subnet" "db" {
  for_each                = var.subnets
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.value.az
  cidr_block              = each.value.db_cidr
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-db-${each.key}" }
}
resource "aws_eip" "nat" {
  for_each = var.enable_nat_gateways ? var.subnets : {}
  domain   = "vpc"
}
resource "aws_nat_gateway" "this" {
  for_each      = var.enable_nat_gateways ? var.subnets : {}
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id
  depends_on    = [aws_internet_gateway.this]
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
}
resource "aws_route_table_association" "public" {
  for_each       = var.subnets
  subnet_id      = aws_subnet.public[each.key].id
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table" "app" {
  for_each = var.subnets
  vpc_id   = aws_vpc.this.id
  dynamic "route" {
    for_each = var.enable_nat_gateways ? [each.key] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.this[route.value].id
    }
  }
}
resource "aws_route_table_association" "app" {
  for_each       = var.subnets
  subnet_id      = aws_subnet.app[each.key].id
  route_table_id = aws_route_table.app[each.key].id
}
resource "aws_route_table" "db" { vpc_id = aws_vpc.this.id }
resource "aws_route_table_association" "db" {
  for_each       = var.subnets
  subnet_id      = aws_subnet.db[each.key].id
  route_table_id = aws_route_table.db.id
}
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for r in aws_route_table.app : r.id]
  # ECR image layers also use S3. Workload IAM/bucket policies restrict application access.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action = concat(
        ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"],
        sort(tolist(var.additional_s3_endpoint_actions))
      )
      Resource = "*"
    }]
  })
}
