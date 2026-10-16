output "cluster_name" { value = aws_eks_cluster.this.name }
output "cluster_security_group_id" { value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id }
output "node_role_name" {
  value      = aws_iam_role.node.name
  depends_on = [aws_eks_access_policy_association.node]
}

output "admin_role_arn" {
  value      = aws_iam_role.admin.arn
  sensitive  = true
  depends_on = [aws_eks_access_policy_association.admin, aws_iam_role_policy.admin_describe]
}
