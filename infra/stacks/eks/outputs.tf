output "cluster_name" {
  value = module.eks.cluster_name
}
output "node_role_name" { value = module.eks.node_role_name }

output "cluster_security_group_id" {
  value = module.eks.cluster_security_group_id
}
