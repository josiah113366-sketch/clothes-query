data "aws_db_instance" "existing" {
  db_instance_identifier = var.db_instance_identifier
  lifecycle {
    postcondition {
      condition     = startswith(self.availability_zone, "ap-northeast-1") && self.engine == "postgres"
      error_message = "Only monitor the existing Tokyo PostgreSQL DB."
    }
  }
}
data "aws_eks_cluster" "existing" { name = var.cluster_name }
module "infrastructure_alerts" {
  source                 = "../../modules/infrastructure-alerts"
  name                   = "clothes-query-dev"
  cluster_name           = data.aws_eks_cluster.existing.name
  db_instance_identifier = data.aws_db_instance.existing.db_instance_identifier
  email_recipients       = var.email_recipients
  wal_budget_mib         = var.wal_budget_mib
}
