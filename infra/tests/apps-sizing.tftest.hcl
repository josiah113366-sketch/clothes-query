mock_provider "aws" {
  mock_data "aws_eks_addon_version" { defaults = { version = "v0.8.0-eksbuild.1" } }
}
mock_provider "kubernetes" {}

variables {
  name             = "test-apps"
  cluster_name     = "test-cluster"
  bucket_name      = "test-bucket"
  bucket_arn       = "arn:aws:s3:::test-bucket"
  database_address = "database.invalid"
  database_name    = "clothes"
  region           = "ap-northeast-1"
  s3_prefix        = "application/"
  node_pool_name   = "test-compute"
  deploy_workloads = true
  images = {
    web = format("example/web@sha256:%s", join("", [for i in range(64) : "a"]))
    was = format("example/was@sha256:%s", join("", [for i in range(64) : "b"]))
  }
  certificate_arn   = "mock-certificate"
  hostname          = "test.invalid"
  alb_inbound_cidrs = ["192.0.2.1/32"]
}
run "size_was_resources_without_scaling_web" {
  command = plan
  module { source = "../modules/apps" }
  variables {
    workload_settings = {
      was = { cpu_request_millicores = 250, memory_request_mib = 256 }
    }
  }
  assert {
    condition     = kubernetes_deployment_v1.was["was"].spec[0].replicas == "2" && kubernetes_deployment_v1.this["web"].spec[0].replicas == "2"
    error_message = "WAS must scale independently while WEB retains its HA default."
  }
  assert {
    condition     = kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].container[0].resources[0].requests.cpu == "250m"
    error_message = "WAS CPU requests must reflect the sizing input."
  }
  assert {
    condition     = kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].node_selector["karpenter.sh/nodepool"] == "test-compute"
    error_message = "Workloads must use the bounded custom pool."
  }
}
run "reject_single_replica" {
  command = plan
  module { source = "../modules/apps" }
  variables {
    workload_settings = { web = { replicas = 1 } }
  }
  expect_failures = [var.workload_settings]
}
run "reject_request_above_limit" {
  command = plan
  module { source = "../modules/apps" }
  variables {
    workload_settings = { was = { cpu_request_millicores = 1000, cpu_limit_millicores = 500 } }
  }
  expect_failures = [var.workload_settings]
}

run "hpa_bounds_and_cpu_policy" {
  command = plan
  module { source = "../modules/apps" }
  assert {
    condition     = kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].min_replicas == 2 && kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].max_replicas == 3 && kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].metric[0].resource[0].target[0].average_utilization == 70 && kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].behavior[0].scale_down[0].stabilization_window_seconds == 300
    error_message = "HPA must retain HA bounds, CPU target and stable downscaling."
  }
  assert {
    condition     = kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].scale_target_ref[0].name == "was" && aws_eks_addon.metrics.addon_name == "metrics-server"
    error_message = "HPA must target WAS and have its metrics prerequisite."
  }
}
run "hpa_custom_bounds" {
  command = plan
  module { source = "../modules/apps" }
  variables { was_autoscaling = { min_replicas = 3, max_replicas = 5, target_cpu_utilization = 60 } }
  assert {
    condition     = kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].min_replicas == 3 && kubernetes_horizontal_pod_autoscaler_v2.was[0].spec[0].max_replicas == 5 && kubernetes_deployment_v1.was["was"].spec[0].replicas == "3"
    error_message = "Custom HPA bounds must also set the initial replica count."
  }
}
run "reject_hpa_invalid_bounds" {
  command = plan
  module { source = "../modules/apps" }
  variables { was_autoscaling = { min_replicas = 3, max_replicas = 2 } }
  expect_failures = [var.was_autoscaling]
}
run "foundation_has_no_hpa" {
  command = plan
  module { source = "../modules/apps" }
  variables { deploy_workloads = false }
  assert {
    condition     = length(kubernetes_horizontal_pod_autoscaler_v2.was) == 0 && length(kubernetes_deployment_v1.was) == 0 && aws_eks_addon.metrics.addon_name == "metrics-server"
    error_message = "Foundation prepares metrics without deploying workloads or HPA."
  }
}
