output "node_pool_name" {
  value      = var.name
  depends_on = [kubernetes_manifest.node_pool]
}
output "capacity_limits" {
  value = { cpu = var.node_pool_cpu_limit, memory_gib = var.node_pool_memory_limit_gib }
}
