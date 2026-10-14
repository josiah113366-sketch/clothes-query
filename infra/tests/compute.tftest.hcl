mock_provider "kubernetes" {}

variables {
  name                      = "test-compute"
  node_role_name            = "test-node-role"
  app_subnet_ids            = ["subnet-test-a"]
  cluster_security_group_id = "sg-test-cluster"
  availability_zones        = ["ap-northeast-1a"]
}

run "bounded_on_demand_pool" {
  command = plan
  module { source = "../modules/compute" }
  assert {
    condition     = kubernetes_manifest.node_pool.manifest.spec.limits.cpu == "8" && kubernetes_manifest.node_pool.manifest.spec.limits.memory == "32Gi"
    error_message = "The initial pool must be bounded to 8 vCPU and 32 GiB."
  }
  assert {
    condition     = contains([for r in kubernetes_manifest.node_pool.manifest.spec.template.spec.requirements : jsonencode(r)], jsonencode({ key = "karpenter.sh/capacity-type", operator = "In", values = ["on-demand"] }))
    error_message = "The pool must explicitly prohibit Spot capacity."
  }
  assert {
    condition     = kubernetes_manifest.node_class.manifest.spec.securityGroupSelectorTerms[0].id == "sg-test-cluster" && length(kubernetes_manifest.node_class.manifest.spec.subnetSelectorTerms) == 1
    error_message = "Custom nodes must preserve the RDS-approved SG and the single workload subnet."
  }
  assert {
    condition     = contains([for r in kubernetes_manifest.node_pool.manifest.spec.template.spec.requirements : jsonencode(r)], jsonencode({ key = "topology.kubernetes.io/zone", operator = "In", values = ["ap-northeast-1a"] }))
    error_message = "Worker nodes must remain in the single workload AZ."
  }
  assert {
    condition     = kubernetes_manifest.node_pool.manifest.spec.disruption.consolidationPolicy == "WhenEmptyOrUnderutilized" && kubernetes_manifest.node_pool.manifest.spec.disruption.consolidateAfter == "10m"
    error_message = "Underutilized capacity must be eligible for delayed consolidation."
  }
}
run "increase_capacity" {
  command = plan
  module { source = "../modules/compute" }
  variables {
    node_pool_cpu_limit        = 12
    node_pool_memory_limit_gib = 48
  }
  assert {
    condition     = kubernetes_manifest.node_pool.manifest.spec.limits.cpu == "12" && kubernetes_manifest.node_pool.manifest.spec.limits.memory == "48Gi"
    error_message = "Capacity inputs must flow through to the NodePool."
  }
}
run "reduce_capacity_with_replacement_headroom" {
  command = plan
  module { source = "../modules/compute" }
  variables {
    node_pool_cpu_limit        = 6
    node_pool_memory_limit_gib = 24
  }
  assert {
    condition     = output.capacity_limits.cpu == 6 && output.capacity_limits.memory_gib == 24
    error_message = "The lower capacity setting must remain configurable."
  }
}
run "reject_single_node_budget" {
  command = plan
  module { source = "../modules/compute" }
  variables { node_pool_cpu_limit = 2 }
  expect_failures = [var.node_pool_cpu_limit]
}
