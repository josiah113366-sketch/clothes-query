mock_provider "kubernetes" {}

variables {
  name                      = "test-compute"
  node_role_name            = "test-node-role"
  app_subnet_ids            = ["subnet-test-a", "subnet-test-c"]
  cluster_security_group_id = "sg-test-cluster"
  availability_zones        = ["ap-northeast-1a", "ap-northeast-1c"]
}

run "bounded_on_demand_pool" {
  command = plan
  module { source = "../modules/compute" }
  assert {
    condition     = length(kubernetes_manifest.spark_node_pool) == 0 && output.spark_node_pool_name == null
    error_message = "Default compute plans must not create Spark capacity."
  }
  assert {
    condition     = kubernetes_manifest.node_pool.manifest.spec.limits.cpu == "6" && kubernetes_manifest.node_pool.manifest.spec.limits.memory == "24Gi"
    error_message = "The compact pool must have a nominal three-node budget of 6 vCPU and 24 GiB."
  }
  assert {
    condition     = contains([for r in kubernetes_manifest.node_pool.manifest.spec.template.spec.requirements : jsonencode(r)], jsonencode({ key = "node.kubernetes.io/instance-type", operator = "In", values = ["t3a.large"] }))
    error_message = "The compact pool must use only t3a.large instances."
  }
  assert {
    condition     = kubernetes_manifest.node_class.manifest.spec.advancedNetworking.associatePublicIPAddress == false && contains([for r in kubernetes_manifest.node_pool.manifest.spec.template.spec.requirements : jsonencode(r)], jsonencode({ key = "topology.kubernetes.io/zone", operator = "In", values = ["ap-northeast-1a", "ap-northeast-1c"] }))
    error_message = "Cost reduction must preserve private nodes and both eligible AZs."
  }
  assert {
    condition     = !contains(keys(kubernetes_manifest.node_pool.manifest.spec), "replicas")
    error_message = "The pool must remain demand-driven instead of reserving three nodes."
  }
  assert {
    condition     = contains([for r in kubernetes_manifest.node_pool.manifest.spec.template.spec.requirements : jsonencode(r)], jsonencode({ key = "karpenter.sh/capacity-type", operator = "In", values = ["on-demand"] }))
    error_message = "The pool must explicitly prohibit Spot capacity."
  }
  assert {
    condition     = kubernetes_manifest.node_class.manifest.spec.securityGroupSelectorTerms[0].id == "sg-test-cluster" && length(kubernetes_manifest.node_class.manifest.spec.subnetSelectorTerms) == 2
    error_message = "Custom nodes must preserve the RDS-approved SG and both app subnets."
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
    node_pool_cpu_limit        = 4
    node_pool_memory_limit_gib = 16
  }
  assert {
    condition     = output.capacity_limits.cpu == 4 && output.capacity_limits.memory_gib == 16
    error_message = "The lower capacity setting must remain configurable."
  }
}
run "reject_budget_without_replacement_headroom" {
  command = plan
  module { source = "../modules/compute" }
  variables { node_pool_cpu_limit = 2 }
  expect_failures = [var.node_pool_cpu_limit]
}

run "opt_in_spark_pool_is_isolated_and_demand_driven" {
  command = plan
  module { source = "../modules/compute" }
  variables { spark_node_pool = { enabled = true } }
  assert {
    condition     = kubernetes_manifest.spark_node_pool[0].manifest.metadata.name == "test-compute-spark" && kubernetes_manifest.spark_node_pool[0].manifest.spec.template.spec.taints[0].value == "spark"
    error_message = "Spark must have a separate tainted pool using the approved NodeClass."
  }
  assert {
    condition     = kubernetes_manifest.spark_node_pool[0].manifest.spec.limits.cpu == "4" && kubernetes_manifest.spark_node_pool[0].manifest.spec.limits.memory == "8Gi" && !contains(keys(kubernetes_manifest.spark_node_pool[0].manifest.spec), "replicas")
    error_message = "Spark must remain demand-driven with explicit capacity budgets."
  }
  assert {
    condition     = kubernetes_manifest.spark_node_pool[0].manifest.spec.disruption.consolidationPolicy == "WhenEmpty" && kubernetes_manifest.node_pool.manifest.spec.limits.cpu == "6"
    error_message = "Spark consolidation must not evict running jobs or modify common capacity."
  }
}

run "reject_spark_budget_smaller_than_one_node" {
  command = plan
  module { source = "../modules/compute" }
  variables { spark_node_pool = { enabled = true, instance_types = ["r6a.large"], memory_limit_gib = 8 } }
  expect_failures = [var.spark_node_pool]
}

run "shared_memory_candidate_does_not_create_dedicated_pool" {
  command = plan
  module { source = "../modules/compute" }
  variables {
    instance_types             = ["r6a.large"]
    node_pool_cpu_limit        = 4
    node_pool_memory_limit_gib = 32
  }
  assert {
    condition     = length(kubernetes_manifest.spark_node_pool) == 0 && kubernetes_manifest.node_pool.manifest.spec.limits.memory == "32Gi"
    error_message = "The shared-memory candidate must not silently add a dedicated pool."
  }
  assert {
    condition     = contains([for r in kubernetes_manifest.node_pool.manifest.spec.template.spec.requirements : jsonencode(r)], jsonencode({ key = "node.kubernetes.io/instance-type", operator = "In", values = ["r6a.large"] }))
    error_message = "The shared-memory candidate must explicitly select its reviewed type."
  }
}
