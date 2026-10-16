terraform {
  required_providers {
    kubernetes = { source = "hashicorp/kubernetes" }
  }
}
resource "kubernetes_manifest" "node_class" {
  manifest = {
    apiVersion = "eks.amazonaws.com/v1"
    kind       = "NodeClass"
    metadata   = { name = var.name }
    spec = {
      role                       = var.node_role_name
      subnetSelectorTerms        = [for id in var.app_subnet_ids : { id = id }]
      securityGroupSelectorTerms = [{ id = var.cluster_security_group_id }]
      advancedNetworking         = { associatePublicIPAddress = false }
    }
  }
}
resource "kubernetes_manifest" "node_pool" {
  manifest = {
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = var.name }
    spec = {
      template = {
        spec = {
          nodeClassRef = { group = "eks.amazonaws.com", kind = "NodeClass", name = var.name }
          requirements = [
            { key = "node.kubernetes.io/instance-type", operator = "In", values = sort(tolist(var.instance_types)) },
            { key = "kubernetes.io/arch", operator = "In", values = ["amd64"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["on-demand"] },
            { key = "topology.kubernetes.io/zone", operator = "In", values = var.availability_zones }
          ]
        }
      }
      limits = { cpu = tostring(var.node_pool_cpu_limit), memory = "${var.node_pool_memory_limit_gib}Gi" }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter    = var.consolidate_after
        budgets             = [{ nodes = "1" }]
      }
    }
  }
  depends_on = [kubernetes_manifest.node_class]
}
