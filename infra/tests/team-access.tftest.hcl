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
