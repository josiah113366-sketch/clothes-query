data "aws_partition" "current" {}
resource "aws_iam_role" "cluster" {
  name = "${var.name}-cluster"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"] }]
  })
}
locals {
  cluster_policies = toset(["AmazonEKSClusterPolicy", "AmazonEKSComputePolicy", "AmazonEKSBlockStoragePolicyV2", "AmazonEKSLoadBalancingPolicy", "AmazonEKSNetworkingPolicy"])
  node_policies    = toset(["AmazonEKSWorkerNodeMinimalPolicy", "AmazonEC2ContainerRegistryPullOnly"])
}
resource "aws_iam_role_policy_attachment" "cluster" {
  for_each   = local.cluster_policies
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}
resource "aws_iam_role" "node" {
  name = "${var.name}-node"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy_attachment" "node" {
  for_each   = local.node_policies
  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}
resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = 30
}
resource "aws_eks_cluster" "this" {
  name                          = var.name
  role_arn                      = aws_iam_role.cluster.arn
  version                       = var.kubernetes_version
  bootstrap_self_managed_addons = false
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }
  compute_config {
    enabled    = true
    node_pools = []
  }
  kubernetes_network_config {
    elastic_load_balancing { enabled = true }
  }
  storage_config {
    block_storage { enabled = true }
  }
  vpc_config {
    subnet_ids              = var.app_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.allow_public_api_from_anywhere ? ["0.0.0.0/0"] : var.public_access_cidrs
  }
  upgrade_policy { support_type = "STANDARD" }
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  depends_on                = [aws_iam_role_policy_attachment.cluster, aws_iam_role_policy_attachment.node, aws_cloudwatch_log_group.cluster]
}
resource "aws_eks_access_entry" "node" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_iam_role.node.arn
  type          = "EC2"
}
resource "aws_eks_access_policy_association" "node" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_iam_role.node.arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSAutoNodePolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.node]
}
resource "aws_eks_access_entry" "admin" {
  for_each      = merge({ dedicated = aws_iam_role.admin.arn }, { for arn in var.admin_role_arns : arn => arn })
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "admin" {
  for_each      = merge({ dedicated = aws_iam_role.admin.arn }, { for arn in var.admin_role_arns : arn => arn })
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.admin]
}

resource "aws_iam_role" "admin" {
  name = "${var.name}-admin"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = sort(tolist(var.admin_trusted_principal_arns)) }
      Action    = "sts:AssumeRole"
    }]
  })
}
resource "aws_iam_role_policy" "admin_describe" {
  name = "describe-project-cluster"
  role = aws_iam_role.admin.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["eks:DescribeCluster"], Resource = [aws_eks_cluster.this.arn] }]
  })
}
