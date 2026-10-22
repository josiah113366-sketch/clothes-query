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

locals {
  operational_reads = {
    core = {
      groups = [""]
      resources = [
        "nodes", "namespaces", "pods", "pods/log", "services", "endpoints", "events",
        "persistentvolumes", "persistentvolumeclaims"
      ]
    }
    workloads = {
      groups    = ["apps"]
      resources = ["deployments", "replicasets", "statefulsets", "daemonsets", "controllerrevisions"]
    }
    batch = {
      groups    = ["batch"]
      resources = ["jobs", "cronjobs"]
    }
    ingress = {
      groups    = ["networking.k8s.io"]
      resources = ["ingresses", "ingressclasses", "networkpolicies"]
    }
    scaling = {
      groups    = ["autoscaling"]
      resources = ["horizontalpodautoscalers"]
    }
    disruption = {
      groups    = ["policy"]
      resources = ["poddisruptionbudgets"]
    }
    metrics = {
      groups    = ["metrics.k8s.io"]
      resources = ["nodes", "pods"]
    }
    kafka = {
      groups    = ["kafka.strimzi.io"]
      resources = ["kafkas", "kafkanodepools", "kafkatopics", "kafkausers", "kafkaconnects", "kafkaconnectors"]
    }
    node_pool = {
      groups    = ["karpenter.sh"]
      resources = ["nodepools", "nodeclaims"]
    }
    node_class = {
      groups    = ["eks.amazonaws.com"]
      resources = ["nodeclasses"]
    }
  }
}

resource "kubernetes_cluster_role_v1" "operations_view" {
  metadata { name = "clothes-query-operations-view" }
  dynamic "rule" {
    for_each = local.operational_reads
    content {
      api_groups = rule.value.groups
      resources  = rule.value.resources
      verbs      = ["get", "list", "watch"]
    }
  }
}

resource "kubernetes_cluster_role_binding_v1" "operations_view" {
  metadata { name = "clothes-query-operations-view" }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role_v1.operations_view.metadata[0].name
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = one(aws_eks_access_entry.deployer.kubernetes_groups)
  }
}
