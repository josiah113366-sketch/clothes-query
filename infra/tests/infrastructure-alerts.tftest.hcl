mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "000000000000" } }
}
run "scoped_infra_notifications" {
  command = plan
  module { source = "../modules/infrastructure-alerts" }
  override_resource {
    target          = aws_sns_topic.this
    override_during = plan
    values          = { arn = "arn:aws:sns:ap-northeast-1:000000000000:test-infra-alerts" }
  }
  variables {
    name                   = "test-infra"
    cluster_name           = "test-eks"
    db_instance_identifier = "test-rds"
    email_recipients       = ["recipient@example.invalid"]
    wal_budget_mib         = 256
  }
  assert {
    condition = (
      length(aws_cloudwatch_metric_alarm.rds) == 5 &&
      aws_cloudwatch_metric_alarm.rds["wal-high-or-missing"].threshold == 201326592 &&
      aws_cloudwatch_metric_alarm.rds["wal-high-or-missing"].treat_missing_data == "breaching" &&
      aws_cloudwatch_metric_alarm.rds["storage-critical"].dimensions.DBInstanceIdentifier == "test-rds"
    )
    error_message = "Only the existing RDS must be monitored with the configured WAL budget."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.publish.policy).Statement[0].Action == ["sns:Publish"] &&
      jsondecode(aws_iam_role.alertmanager.assume_role_policy).Statement[0].Condition.StringEquals["aws:RequestTag/kubernetes-namespace"] == "monitoring" &&
      aws_eks_pod_identity_association.alertmanager.service_account == "monitoring-alertmanager"
    )
    error_message = "Alert delivery must not gain data/admin access."
  }
}
