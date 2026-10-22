output "namespace" { value = kubernetes_namespace_v1.application.metadata[0].name }
output "kubernetes_group" { value = one(aws_eks_access_entry.deployer.kubernetes_groups) }
