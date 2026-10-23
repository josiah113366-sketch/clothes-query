# Opt-in only. Existing common NodeClass keeps private subnet/SG settings.
resource "kubernetes_manifest" "spark_node_pool" {
  count = var.spark_node_pool.enabled ? 1 : 0
  manifest = {
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "${var.name}-spark" }
    spec = {
      template = {
        spec = {
          nodeClassRef = { group = "eks.amazonaws.com", kind = "NodeClass", name = var.name }
          taints       = [{ key = "clothes-query/dedicated", value = "spark", effect = "NoSchedule" }]
          requirements = [
            { key = "node.kubernetes.io/instance-type", operator = "In", values = sort(tolist(var.spark_node_pool.instance_types)) },
            { key = "kubernetes.io/arch", operator = "In", values = ["amd64"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["on-demand"] },
            { key = "topology.kubernetes.io/zone", operator = "In", values = var.availability_zones }
          ]
        }
      }
      limits = { cpu = tostring(var.spark_node_pool.cpu_limit), memory = "${var.spark_node_pool.memory_limit_gib}Gi" }
      disruption = {
        consolidationPolicy = "WhenEmpty"
        consolidateAfter    = var.spark_node_pool.consolidate_after
        budgets             = [{ nodes = "1" }]
      }
    }
  }
  depends_on = [kubernetes_manifest.node_class]
}

output "spark_node_pool_name" {
  value = var.spark_node_pool.enabled ? "${var.name}-spark" : null
}
