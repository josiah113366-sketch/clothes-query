terraform {
  required_providers {
    aws        = { source = "hashicorp/aws" }
    kubernetes = { source = "hashicorp/kubernetes" }
  }
}
resource "kubernetes_namespace_v1" "this" {
  metadata {
    name   = var.namespace
    labels = { "app.kubernetes.io/part-of" = var.name }
  }
}
resource "aws_iam_role" "was" {
  name = "${var.name}-was"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = {
        StringEquals = {
          "aws:RequestTag/kubernetes-namespace"       = var.namespace
          "aws:RequestTag/kubernetes-service-account" = "was"
        }
      }
    }]
  })
}
resource "aws_iam_role_policy" "s3" {
  name = "application-prefix"
  role = aws_iam_role.was.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = ["${var.bucket_arn}/${var.s3_prefix}*"] },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [var.bucket_arn], Condition = { StringLike = { "s3:prefix" = ["${var.s3_prefix}*"] } } },
      { Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = [var.bucket_arn] }
    ]
  })
}
resource "kubernetes_service_account_v1" "was" {
  metadata {
    name      = "was"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
}
resource "aws_eks_pod_identity_association" "was" {
  cluster_name    = var.cluster_name
  namespace       = kubernetes_namespace_v1.this.metadata[0].name
  service_account = kubernetes_service_account_v1.was.metadata[0].name
  role_arn        = aws_iam_role.was.arn
  depends_on      = [aws_iam_role_policy.s3]
}
resource "kubernetes_config_map_v1" "was" {
  metadata {
    name      = "was-config"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  data = {
    DB_HOST    = var.database_address
    DB_PORT    = "5432"
    DB_NAME    = var.database_name
    AWS_REGION = var.region
    S3_BUCKET  = var.bucket_name
    S3_PREFIX  = var.s3_prefix
  }
}
resource "kubernetes_config_map_v1" "web" {
  metadata {
    name      = "web-nginx"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  data = {
    "default.conf" = <<-NGINX
      server {
        listen 80;
        server_name _;
        location = /health {
          access_log off;
          return 200 'web-ok';
        }
        location /api/ {
          proxy_pass http://was-service:8000;
          proxy_http_version 1.1;
          proxy_set_header Host $host;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        }
        location / {
          root /usr/share/nginx/html;
          index index.html;
          try_files $uri $uri/ /index.html;
        }
      }
    NGINX
  }
}
locals {
  workloads = var.deploy_workloads ? toset(["web", "was"]) : toset([])
  ports     = { web = 80, was = 8000 }
}
resource "kubernetes_service_v1" "this" {
  for_each = local.workloads
  metadata {
    name      = "${each.key}-service"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    type     = "ClusterIP"
    selector = { app = each.key }
    port {
      name        = "http"
      port        = local.ports[each.key]
      target_port = "http"
    }
  }
}
resource "kubernetes_deployment_v1" "this" {
  for_each         = var.deploy_workloads ? toset(["web"]) : toset([])
  wait_for_rollout = true
  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    replicas = var.workload_settings[each.key].replicas
    selector { match_labels = { app = each.key } }
    strategy {
      type = "RollingUpdate"
      rolling_update {
        max_unavailable = "0"
        max_surge       = "1"
      }
    }
    template {
      metadata {
        labels = { app = each.key }
        annotations = {
          "checksum/config" = sha256(jsonencode(each.key == "web" ? kubernetes_config_map_v1.web.data : kubernetes_config_map_v1.was.data))
        }
      }
      spec {
        node_selector                   = { "karpenter.sh/nodepool" = var.node_pool_name }
        service_account_name            = each.key == "was" ? kubernetes_service_account_v1.was.metadata[0].name : "default"
        automount_service_account_token = each.key == "was"
        topology_spread_constraint {
          max_skew           = 1
          min_domains        = 2
          topology_key       = "topology.kubernetes.io/zone"
          when_unsatisfiable = "DoNotSchedule"
          label_selector { match_labels = { app = each.key } }
        }
        affinity {
          pod_anti_affinity {
            required_during_scheduling_ignored_during_execution {
              topology_key = "kubernetes.io/hostname"
              label_selector { match_labels = { app = each.key } }
            }
          }
        }
        container {
          name  = each.key
          image = var.images[each.key]
          port {
            name           = "http"
            container_port = local.ports[each.key]
          }
          dynamic "env_from" {
            for_each = each.key == "was" ? [1] : []
            content {
              config_map_ref { name = kubernetes_config_map_v1.was.metadata[0].name }
            }
          }
          dynamic "env_from" {
            for_each = each.key == "was" ? [1] : []
            content {
              secret_ref { name = var.database_secret_name }
            }
          }
          dynamic "volume_mount" {
            for_each = each.key == "web" ? [1] : []
            content {
              name       = "nginx"
              mount_path = "/etc/nginx/conf.d/default.conf"
              sub_path   = "default.conf"
              read_only  = true
            }
          }
          readiness_probe {
            http_get {
              path = "/health"
              port = "http"
            }
            initial_delay_seconds = 5
            period_seconds        = 10
          }
          liveness_probe {
            http_get {
              path = "/health"
              port = "http"
            }
            initial_delay_seconds = 30
            period_seconds        = 20
          }
          resources {
            requests = {
              cpu    = "${var.workload_settings[each.key].cpu_request_millicores}m"
              memory = "${var.workload_settings[each.key].memory_request_mib}Mi"
            }
            limits = {
              cpu    = "${var.workload_settings[each.key].cpu_limit_millicores}m"
              memory = "${var.workload_settings[each.key].memory_limit_mib}Mi"
            }
          }
        }
        dynamic "volume" {
          for_each = each.key == "web" ? [1] : []
          content {
            name = "nginx"
            config_map { name = kubernetes_config_map_v1.web.metadata[0].name }
          }
        }
      }
    }
  }
  depends_on = [aws_eks_pod_identity_association.was, kubernetes_service_v1.this]
  timeouts { create = "15m" }
}
resource "kubernetes_deployment_v1" "was" {
  for_each         = var.deploy_workloads ? toset(["was"]) : toset([])
  wait_for_rollout = true
  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    replicas = var.was_autoscaling.min_replicas
    selector { match_labels = { app = each.key } }
    strategy {
      type = "RollingUpdate"
      rolling_update {
        max_unavailable = "0"
        max_surge       = "1"
      }
    }
    template {
      metadata {
        labels = { app = each.key }
        annotations = {
          "checksum/config" = sha256(jsonencode(each.key == "web" ? kubernetes_config_map_v1.web.data : kubernetes_config_map_v1.was.data))
        }
      }
      spec {
        node_selector                   = { "karpenter.sh/nodepool" = var.node_pool_name }
        service_account_name            = each.key == "was" ? kubernetes_service_account_v1.was.metadata[0].name : "default"
        automount_service_account_token = each.key == "was"
        topology_spread_constraint {
          max_skew           = 1
          min_domains        = 2
          topology_key       = "topology.kubernetes.io/zone"
          when_unsatisfiable = "DoNotSchedule"
          label_selector { match_labels = { app = each.key } }
        }
        affinity {
          pod_anti_affinity {
            required_during_scheduling_ignored_during_execution {
              topology_key = "kubernetes.io/hostname"
              label_selector { match_labels = { app = each.key } }
            }
          }
        }
        container {
          name  = each.key
          image = var.images[each.key]
          port {
            name           = "http"
            container_port = local.ports[each.key]
          }
          dynamic "env_from" {
            for_each = each.key == "was" ? [1] : []
            content {
              config_map_ref { name = kubernetes_config_map_v1.was.metadata[0].name }
            }
          }
          dynamic "env_from" {
            for_each = each.key == "was" ? [1] : []
            content {
              secret_ref { name = var.database_secret_name }
            }
          }
          dynamic "volume_mount" {
            for_each = each.key == "web" ? [1] : []
            content {
              name       = "nginx"
              mount_path = "/etc/nginx/conf.d/default.conf"
              sub_path   = "default.conf"
              read_only  = true
            }
          }
          readiness_probe {
            http_get {
              path = "/health"
              port = "http"
            }
            initial_delay_seconds = 5
            period_seconds        = 10
          }
          liveness_probe {
            http_get {
              path = "/health"
              port = "http"
            }
            initial_delay_seconds = 30
            period_seconds        = 20
          }
          resources {
            requests = {
              cpu    = "${var.workload_settings[each.key].cpu_request_millicores}m"
              memory = "${var.workload_settings[each.key].memory_request_mib}Mi"
            }
            limits = {
              cpu    = "${var.workload_settings[each.key].cpu_limit_millicores}m"
              memory = "${var.workload_settings[each.key].memory_limit_mib}Mi"
            }
          }
        }
        dynamic "volume" {
          for_each = each.key == "web" ? [1] : []
          content {
            name = "nginx"
            config_map { name = kubernetes_config_map_v1.web.metadata[0].name }
          }
        }
      }
    }
  }
  depends_on = [aws_eks_pod_identity_association.was, kubernetes_service_v1.this]
  lifecycle { ignore_changes = [spec[0].replicas] }
  timeouts { create = "15m" }
}
resource "kubernetes_pod_disruption_budget_v1" "this" {
  for_each = local.workloads
  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    min_available = "1"
    selector { match_labels = { app = each.key } }
  }
}
resource "kubernetes_manifest" "ingress_params" {
  count = var.deploy_workloads ? 1 : 0
  manifest = {
    apiVersion = "eks.amazonaws.com/v1"
    kind       = "IngressClassParams"
    metadata   = { name = var.name }
    spec = {
      scheme            = "internet-facing"
      targetType        = "ip"
      certificateARNs   = [var.certificate_arn]
      inboundCIDRs      = var.alb_inbound_cidrs
      namespaceSelector = { matchLabels = { "app.kubernetes.io/part-of" = var.name } }
    }
  }
}
resource "kubernetes_ingress_class_v1" "this" {
  count = var.deploy_workloads ? 1 : 0
  metadata { name = var.name }
  spec {
    controller = "eks.amazonaws.com/alb"
    parameters {
      api_group = "eks.amazonaws.com"
      kind      = "IngressClassParams"
      name      = kubernetes_manifest.ingress_params[0].manifest.metadata.name
      scope     = "Cluster"
    }
  }
}
resource "kubernetes_ingress_v1" "this" {
  count = var.deploy_workloads ? 1 : 0
  metadata {
    name      = "web"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    annotations = {
      "alb.ingress.kubernetes.io/listen-ports"     = jsonencode([{ HTTPS = 443 }])
      "alb.ingress.kubernetes.io/healthcheck-path" = "/health"
    }
  }
  spec {
    ingress_class_name = kubernetes_ingress_class_v1.this[0].metadata[0].name
    rule {
      host = var.hostname
      http {
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = kubernetes_service_v1.this["web"].metadata[0].name
              port { number = 80 }
            }
          }
        }
      }
    }
  }
  depends_on = [kubernetes_deployment_v1.this, kubernetes_deployment_v1.was]
}

# Keep WAS replica ownership with HPA; WEB remains Terraform-managed.
moved {
  from = kubernetes_deployment_v1.this["was"]
  to   = kubernetes_deployment_v1.was["was"]
}
data "aws_eks_cluster" "metrics" { name = var.cluster_name }
data "aws_eks_addon_version" "metrics" {
  addon_name         = "metrics-server"
  kubernetes_version = data.aws_eks_cluster.metrics.version
  most_recent        = false
}
resource "aws_eks_addon" "metrics" {
  cluster_name                = var.cluster_name
  addon_name                  = "metrics-server"
  addon_version               = var.metrics_server_version != null ? var.metrics_server_version : data.aws_eks_addon_version.metrics.version
  resolve_conflicts_on_create = "NONE"
  resolve_conflicts_on_update = "NONE"
}
resource "kubernetes_horizontal_pod_autoscaler_v2" "was" {
  count = var.deploy_workloads ? 1 : 0
  metadata {
    name      = "was"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    min_replicas = var.was_autoscaling.min_replicas
    max_replicas = var.was_autoscaling.max_replicas
    scale_target_ref {
      api_version = "apps/v1"
      kind        = "Deployment"
      name        = kubernetes_deployment_v1.was["was"].metadata[0].name
    }
    metric {
      type = "Resource"
      resource {
        name = "cpu"
        target {
          type                = "Utilization"
          average_utilization = var.was_autoscaling.target_cpu_utilization
        }
      }
    }
    behavior {
      scale_up {
        stabilization_window_seconds = 0
        select_policy                = "Max"
        policy {
          type           = "Pods"
          value          = 1
          period_seconds = 60
        }
      }
      scale_down {
        stabilization_window_seconds = var.was_autoscaling.scale_down_stabilization_seconds
        select_policy                = "Max"
        policy {
          type           = "Pods"
          value          = 1
          period_seconds = 60
        }
      }
    }
  }
  depends_on = [aws_eks_addon.metrics]
}
