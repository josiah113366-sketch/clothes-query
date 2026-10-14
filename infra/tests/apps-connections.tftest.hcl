# Verify the existing first-stage contract without an app image or AWS connection.
mock_provider "aws" {
  mock_data "aws_eks_addon_version" { defaults = { version = "v0.8.0-eksbuild.1" } }
}
mock_provider "kubernetes" {}

variables {
  name                 = "test-connections"
  namespace            = "test-connections"
  cluster_name         = "test-cluster"
  bucket_name          = "test-bucket"
  bucket_arn           = "arn:aws:s3:::test-bucket"
  database_address     = "database.invalid"
  database_name        = "clothes"
  database_secret_name = "was-database"
  region               = "ap-northeast-1"
  s3_prefix            = "application/"
  node_pool_name       = "test-compute"
  deploy_workloads     = true
  images = {
    web = format("example/web@sha256:%s", join("", [for i in range(64) : "a"]))
    was = format("example/was@sha256:%s", join("", [for i in range(64) : "b"]))
  }
  certificate_arn   = "mock-certificate"
  hostname          = "test.invalid"
  alb_inbound_cidrs = ["192.0.2.1/32"]
}

run "https_web_was_routing" {
  command = plan
  module { source = "../modules/apps" }
  assert {
    condition = (
      kubernetes_ingress_class_v1.this[0].spec[0].controller == "eks.amazonaws.com/alb" &&
      kubernetes_manifest.ingress_params[0].manifest.spec.scheme == "internet-facing" &&
      kubernetes_manifest.ingress_params[0].manifest.spec.targetType == "ip" &&
      tolist(kubernetes_manifest.ingress_params[0].manifest.spec.certificateARNs) == tolist(["mock-certificate"]) &&
      tolist(kubernetes_manifest.ingress_params[0].manifest.spec.inboundCIDRs) == tolist(["192.0.2.1/32"]) &&
      jsondecode(kubernetes_ingress_v1.this[0].metadata[0].annotations["alb.ingress.kubernetes.io/listen-ports"]) == [{ HTTPS = 443 }]
    )
    error_message = "ALB must retain the chosen HTTPS, certificate, IP targets and inbound ranges."
  }
  assert {
    condition = (
      kubernetes_ingress_v1.this[0].spec[0].rule[0].host == "test.invalid" &&
      kubernetes_ingress_v1.this[0].spec[0].rule[0].http[0].path[0].backend[0].service[0].name == "web-service" &&
      kubernetes_ingress_v1.this[0].spec[0].rule[0].http[0].path[0].backend[0].service[0].port[0].number == 80 &&
      kubernetes_service_v1.this["web"].spec[0].selector.app == "web" &&
      kubernetes_service_v1.this["web"].spec[0].port[0].port == 80 &&
      kubernetes_service_v1.this["web"].spec[0].port[0].target_port == "http"
    )
    error_message = "HTTPS ingress must route to the actual WEB Service and its named container port."
  }
  assert {
    condition = (
      strcontains(kubernetes_config_map_v1.web.data["default.conf"], "proxy_pass http://was-service:8000;") &&
      kubernetes_service_v1.this["was"].spec[0].selector.app == "was" &&
      kubernetes_service_v1.this["was"].spec[0].port[0].port == 8000 &&
      kubernetes_service_v1.this["was"].spec[0].port[0].target_port == "http" &&
      kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].container[0].port[0].name == "http" &&
      kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].container[0].port[0].container_port == 8000
    )
    error_message = "WEB /api/ proxy, WAS Service and WAS container must agree on the destination."
  }
}

run "was_database_and_identity_contract" {
  command = plan
  module { source = "../modules/apps" }
  assert {
    condition = (
      kubernetes_config_map_v1.was.data.DB_HOST == "database.invalid" &&
      kubernetes_config_map_v1.was.data.DB_PORT == "5432" &&
      kubernetes_config_map_v1.was.data.DB_NAME == "clothes" &&
      contains([for e in kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].container[0].env_from : try(e.config_map_ref[0].name, "")], "was-config") &&
      contains([for e in kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].container[0].env_from : try(e.secret_ref[0].name, "")], "was-database")
    )
    error_message = "WAS must receive PostgreSQL settings and the externally supplied app-account Secret."
  }
  assert {
    condition = (
      kubernetes_deployment_v1.was["was"].spec[0].template[0].spec[0].service_account_name == "was" &&
      aws_eks_pod_identity_association.was.namespace == "test-connections" &&
      aws_eks_pod_identity_association.was.service_account == "was" &&
      jsondecode(aws_iam_role.was.assume_role_policy).Statement[0].Principal.Service == "pods.eks.amazonaws.com" &&
      jsondecode(aws_iam_role.was.assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-namespace"] == "test-connections" &&
      jsondecode(aws_iam_role.was.assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-service-account"] == "was"
    )
    error_message = "WAS Pod Identity must be associated with and restricted to its namespace and ServiceAccount."
  }
}

run "was_s3_prefix_permissions" {
  command = plan
  module { source = "../modules/apps" }
  assert {
    condition = (
      kubernetes_config_map_v1.was.data.S3_BUCKET == "test-bucket" &&
      kubernetes_config_map_v1.was.data.S3_PREFIX == "application/" &&
      kubernetes_config_map_v1.was.data.AWS_REGION == "ap-northeast-1" &&
      toset(flatten([for s in jsondecode(aws_iam_role_policy.s3.policy).Statement : s.Action])) == toset(["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"])
    )
    error_message = "WAS must receive S3 settings and only its intended Get/Put/List/location permissions."
  }
  assert {
    condition = alltrue(flatten([for s in jsondecode(aws_iam_role_policy.s3.policy).Statement : [
      for action in s.Action : s.Effect == "Allow" && (
        contains(["s3:GetObject", "s3:PutObject"], action)
        ? s.Resource == ["arn:aws:s3:::test-bucket/application/*"]
        : s.Resource == ["arn:aws:s3:::test-bucket"]
      )
    ]]))
    error_message = "Object permissions must stay within the app prefix and bucket permissions within the app bucket."
  }
  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.s3.policy).Statement :
      !contains(s.Action, "s3:ListBucket") || try(s.Condition.StringLike["s3:prefix"] == ["application/*"], false)
    ])
    error_message = "ListBucket must also be scoped to the application prefix."
  }
}

run "reject_empty_certificate" {
  command = plan
  module { source = "../modules/apps" }
  variables { certificate_arn = "" }
  expect_failures = [var.certificate_arn]
}

run "reject_whitespace_certificate" {
  command = plan
  module { source = "../modules/apps" }
  variables { certificate_arn = "   " }
  expect_failures = [var.certificate_arn]
}

run "reject_whitespace_hostname" {
  command = plan
  module { source = "../modules/apps" }
  variables { hostname = "   " }
  expect_failures = [var.hostname]
}

run "reject_unpinned_images" {
  command = plan
  module { source = "../modules/apps" }
  variables { images = { web = "example/web:latest", was = "example/was:latest" } }
  expect_failures = [var.images]
}

run "foundation_without_images_or_tls" {
  command = plan
  module { source = "../modules/apps" }
  variables {
    deploy_workloads  = false
    images            = {}
    certificate_arn   = null
    hostname          = null
    alb_inbound_cidrs = []
  }
  assert {
    condition = (
      length(kubernetes_deployment_v1.this) == 0 &&
      length(kubernetes_deployment_v1.was) == 0 &&
      length(kubernetes_service_v1.this) == 0 &&
      length(kubernetes_manifest.ingress_params) == 0 &&
      length(kubernetes_ingress_class_v1.this) == 0 &&
      length(kubernetes_ingress_v1.this) == 0 &&
      length(kubernetes_horizontal_pod_autoscaler_v2.was) == 0 &&
      aws_eks_addon.metrics.addon_name == "metrics-server"
    )
    error_message = "Foundation must prepare configuration/identity/metrics without exposing or starting app workloads."
  }
}
