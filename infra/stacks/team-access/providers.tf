provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = "clothes-query", Environment = "dev", ManagedBy = "terraform" }
  }
}

data "aws_eks_cluster" "existing" {
  name = data.terraform_remote_state.eks.outputs.cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.existing.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.existing.certificate_authority[0].data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", data.aws_eks_cluster.existing.name, "--region", var.aws_region, "--role-arn", data.terraform_remote_state.eks.outputs.admin_role_arn]
  }
}
