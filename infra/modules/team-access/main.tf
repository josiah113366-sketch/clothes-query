terraform {
  required_providers {
    aws        = { source = "hashicorp/aws" }
    kubernetes = { source = "hashicorp/kubernetes" }
  }
}

resource "kubernetes_namespace_v1" "application" {
  metadata {
    name   = var.namespace
    labels = { "app.kubernetes.io/part-of" = "clothes-query", "app.kubernetes.io/managed-by" = "terraform" }
  }
}

resource "aws_eks_access_entry" "deployer" {
  cluster_name      = var.cluster_name
  principal_arn     = var.principal_arn
  type              = "STANDARD"
  kubernetes_groups = ["clothes-query:was-deployer"]
}

resource "kubernetes_role_binding_v1" "deployer" {
  metadata {
    name      = "was-deployer"
    namespace = kubernetes_namespace_v1.application.metadata[0].name
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "edit"
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = one(aws_eks_access_entry.deployer.kubernetes_groups)
  }
}
