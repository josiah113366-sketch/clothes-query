mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
}
variables {
  name                         = "test-eks"
  app_subnet_ids               = ["subnet-test-a", "subnet-test-c"]
  kubernetes_version           = "1.36"
  public_access_cidrs          = ["192.0.2.1/32"]
  admin_trusted_principal_arns = [format("arn:aws:iam::%s:user/test-admin", join("", [for i in range(12) : "0"]))]
}
run "dedicated_role_and_limited_trust" {
  command = plan
  module { source = "../modules/eks" }
  override_resource {
    target          = aws_iam_role.admin
    values          = { arn = format("arn:aws:iam::%s:role/test-eks-admin", join("", [for i in range(12) : "0"])) }
    override_during = plan
  }
  override_resource {
    target          = aws_eks_cluster.this
    values          = { arn = format("arn:aws:eks:ap-northeast-1:%s:cluster/test-eks", join("", [for i in range(12) : "0"])) }
    override_during = plan
  }
  assert {
    condition     = toset(jsondecode(aws_iam_role.admin.assume_role_policy).Statement[0].Principal.AWS) == var.admin_trusted_principal_arns && jsondecode(aws_iam_role.admin.assume_role_policy).Statement[0].Action == "sts:AssumeRole"
    error_message = "Only explicitly trusted administrators may assume the dedicated role."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.admin_describe.policy).Statement[0].Action == ["eks:DescribeCluster"] && jsondecode(aws_iam_role_policy.admin_describe.policy).Statement[0].Resource == [aws_eks_cluster.this.arn]
    error_message = "AWS permissions must be limited to describing this cluster."
  }
  assert {
    condition     = length(aws_eks_access_entry.admin) == 1 && aws_eks_access_entry.admin["dedicated"].principal_arn == aws_iam_role.admin.arn && aws_eks_access_policy_association.admin["dedicated"].access_scope[0].type == "cluster" && endswith(aws_eks_access_policy_association.admin["dedicated"].policy_arn, "/AmazonEKSClusterAdminPolicy")
    error_message = "The dedicated role must receive explicit cluster administration access."
  }
  assert {
    condition     = !aws_eks_cluster.this.access_config[0].bootstrap_cluster_creator_admin_permissions && length(aws_eks_cluster.this.vpc_config[0].subnet_ids) == 2 && toset(aws_eks_cluster.this.vpc_config[0].public_access_cidrs) == toset(["192.0.2.1/32"])
    error_message = "Two-AZ networking and restricted API access must remain; creator admin stays disabled."
  }
}
run "add_team_admin_without_changing_role" {
  command = plan
  module { source = "../modules/eks" }
  variables {
    admin_trusted_principal_arns = [for name in ["test-admin", "test-team-admin"] : format("arn:aws:iam::%s:user/%s", join("", [for i in range(12) : "0"]), name)]
    public_access_cidrs          = ["192.0.2.1/32", "198.51.100.1/32"]
  }
  assert {
    condition     = length(jsondecode(aws_iam_role.admin.assume_role_policy).Statement[0].Principal.AWS) == 2 && length(aws_eks_cluster.this.vpc_config[0].public_access_cidrs) == 2 && aws_iam_role.admin.name == "test-eks-admin"
    error_message = "Team administrators and networks must be extendable without a new role name."
  }
}
run "reject_account_root_trust" {
  command = plan
  module { source = "../modules/eks" }
  variables { admin_trusted_principal_arns = [format("arn:aws:iam::%s:root", join("", [for i in range(12) : "0"]))] }
  expect_failures = [var.admin_trusted_principal_arns]
}
run "reject_empty_administrators" {
  command = plan
  module { source = "../modules/eks" }
  variables { admin_trusted_principal_arns = [] }
  expect_failures = [var.admin_trusted_principal_arns]
}
run "reject_open_api_cidr" {
  command = plan
  module { source = "../modules/eks" }
  variables { public_access_cidrs = ["0.0.0.0/0"] }
  expect_failures = [var.public_access_cidrs]
}
run "reject_user_as_additional_role" {
  command = plan
  module { source = "../modules/eks" }
  variables { admin_role_arns = [format("arn:aws:iam::%s:user/test-user", join("", [for i in range(12) : "0"]))] }
  expect_failures = [var.admin_role_arns]
}

run "explicit_development_opening_keeps_authentication_and_private_access" {
  command = plan
  module { source = "../modules/eks" }
  variables { allow_public_api_from_anywhere = true }
  assert {
    condition = (
      toset(aws_eks_cluster.this.vpc_config[0].public_access_cidrs) == toset(["0.0.0.0/0"]) &&
      aws_eks_cluster.this.vpc_config[0].endpoint_public_access &&
      aws_eks_cluster.this.vpc_config[0].endpoint_private_access &&
      aws_eks_cluster.this.access_config[0].authentication_mode == "API" &&
      !aws_eks_cluster.this.access_config[0].bootstrap_cluster_creator_admin_permissions &&
      toset(var.public_access_cidrs) == toset(["192.0.2.1/32"])
    )
    error_message = "Opening must be explicit, preserve IAM/private access and retain restricted CIDRs for restoration."
  }
}

run "turn_off_development_opening_restores_restricted_cidrs" {
  command = plan
  module { source = "../modules/eks" }
  variables { allow_public_api_from_anywhere = false }
  assert {
    condition     = toset(aws_eks_cluster.this.vpc_config[0].public_access_cidrs) == toset(var.public_access_cidrs)
    error_message = "Disabling the temporary option must restore the preserved CIDRs."
  }
}
