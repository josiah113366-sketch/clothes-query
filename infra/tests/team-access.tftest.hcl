mock_provider "aws" {}
mock_provider "kubernetes" {}

variables {
  cluster_name  = "test-cluster"
  principal_arn = "arn:aws:iam::000000000000:user/test-deployer"
}

run "namespace_binding_only_without_cluster_admin" {
  command = plan
  module { source = "../modules/team-access" }
  assert {
    condition = (
      aws_eks_access_entry.deployer.type == "STANDARD" &&
      aws_eks_access_entry.deployer.cluster_name == "test-cluster" &&
      toset(aws_eks_access_entry.deployer.kubernetes_groups) == toset(["clothes-query:was-deployer"]) &&
      kubernetes_namespace_v1.application.metadata[0].name == "clothes-query" &&
      kubernetes_role_binding_v1.deployer.metadata[0].namespace == "clothes-query" &&
      kubernetes_role_binding_v1.deployer.role_ref[0].kind == "ClusterRole" &&
      kubernetes_role_binding_v1.deployer.role_ref[0].name == "edit" &&
      one(kubernetes_role_binding_v1.deployer.subject).kind == "Group" &&
      one(kubernetes_role_binding_v1.deployer.subject).name == "clothes-query:was-deployer"
    )
    error_message = "Bind only the intended EKS identity group to edit in the application namespace."
  }
}

run "reject_root" {
  command = plan
  module { source = "../modules/team-access" }
  variables { principal_arn = "arn:aws:iam::000000000000:root" }
  expect_failures = [var.principal_arn]
}

run "cluster_operational_reads_exclude_secrets_and_mutations" {
  command = plan
  module { source = "../modules/team-access" }
  assert {
    condition = (
      kubernetes_cluster_role_binding_v1.operations_view.role_ref[0].name == kubernetes_cluster_role_v1.operations_view.metadata[0].name &&
      one(kubernetes_cluster_role_binding_v1.operations_view.subject).name == "clothes-query:was-deployer" &&
      alltrue([for rule in kubernetes_cluster_role_v1.operations_view.rule :
        toset(rule.verbs) == toset(["get", "list", "watch"]) &&
        !contains(rule.resources, "*") && !contains(rule.resources, "secrets") &&
        !contains(rule.resources, "nodes/proxy") && !contains(rule.resources, "pods/exec") &&
        !contains(rule.api_groups, "*")
      ]) &&
      contains(flatten([for rule in kubernetes_cluster_role_v1.operations_view.rule : rule.resources]), "nodes") &&
      contains(flatten([for rule in kubernetes_cluster_role_v1.operations_view.rule : rule.resources]), "pods/log") &&
      contains(flatten([for rule in kubernetes_cluster_role_v1.operations_view.rule : rule.resources]), "kafkas")
    )
    error_message = "The additional cluster binding must allow operational reads without secret, exec, proxy or write access."
  }
}

run "reject_session" {
  command = plan
  module { source = "../modules/team-access" }
  variables { principal_arn = "arn:aws:sts::000000000000:assumed-role/example/session" }
  expect_failures = [var.principal_arn]
}

run "reject_other_namespace" {
  command = plan
  module { source = "../modules/team-access" }
  variables { namespace = "kafka" }
  expect_failures = [var.namespace]
}
