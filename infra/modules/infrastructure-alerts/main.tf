data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "this" { name = "${var.name}-infra-alerts" }

resource "aws_sns_topic_policy" "this" {
  arn = aws_sns_topic.this.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TokyoCloudWatchAlarmsOnly"
      Effect    = "Allow"
      Principal = { Service = "cloudwatch.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.this.arn
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:cloudwatch:ap-northeast-1:${data.aws_caller_identity.current.account_id}:alarm:${var.name}-infra-rds-*" }
      }
    }]
  })
}

# Index keys keep private email addresses out of Terraform resource addresses.
resource "aws_sns_topic_subscription" "email" {
  count     = nonsensitive(length(var.email_recipients))
  topic_arn = aws_sns_topic.this.arn
  protocol  = "email"
  endpoint  = sort(tolist(var.email_recipients))[count.index]
}

resource "aws_iam_role" "alertmanager" {
  name = "${var.name}-alertmanager"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = { StringEquals = {
        "aws:RequestTag/eks-cluster-arn"            = "arn:aws:eks:ap-northeast-1:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
        "aws:RequestTag/eks-cluster-name"           = var.cluster_name
        "aws:RequestTag/kubernetes-namespace"       = "monitoring"
        "aws:RequestTag/kubernetes-service-account" = "monitoring-alertmanager"
      } }
    }]
  })
}
resource "aws_iam_role_policy" "publish" {
  name = "single-infra-topic-publish"
  role = aws_iam_role.alertmanager.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Action = ["sns:Publish"], Resource = aws_sns_topic.this.arn
    }]
  })
}
resource "aws_eks_pod_identity_association" "alertmanager" {
  cluster_name    = var.cluster_name
  namespace       = "monitoring"
  service_account = "monitoring-alertmanager"
  role_arn        = aws_iam_role.alertmanager.arn
  depends_on      = [aws_iam_role_policy.publish]
}

locals {
  alarms = {
    storage-warning = {
      metric      = "FreeStorageSpace", statistic = "Minimum", operator = "LessThanThreshold"
      threshold   = 5 * 1024 * 1024 * 1024, period = 300, periods = 2, unit = "Bytes", missing = "missing"
      description = "Free storage below 5 GiB for 10 minutes. Inspect storage growth and WAL."
    }
    storage-critical = {
      metric      = "FreeStorageSpace", statistic = "Minimum", operator = "LessThanThreshold"
      threshold   = 2 * 1024 * 1024 * 1024, period = 300, periods = 1, unit = "Bytes", missing = "missing"
      description = "Free storage below 2 GiB in a 5-minute period. Preserve data; inspect promptly."
    }
    wal-high-or-missing = {
      metric      = "OldestReplicationSlotLag", statistic = "Maximum", operator = "GreaterThanOrEqualToThreshold"
      threshold   = var.wal_budget_mib * 1024 * 1024 * 0.75, period = 60, periods = 2, unit = "Bytes", missing = "breaching"
      description = "Instance replication-slot WAL lag at 75% of configured budget for 2 minutes, OR missing metric (including stopped DB). Inspect reason and slots; do not drop slots automatically. The WAL limit is enforced at checkpoints, not a hard immediate cap."
    }
    cpu-high = {
      metric      = "CPUUtilization", statistic = "Average", operator = "GreaterThanThreshold"
      threshold   = 80, period = 300, periods = 3, unit = "Percent", missing = "missing"
      description = "Average CPU above 80% for 15 minutes. Inspect queries and connections."
    }
    memory-low = {
      metric      = "FreeableMemory", statistic = "Minimum", operator = "LessThanThreshold"
      threshold   = 256 * 1024 * 1024, period = 300, periods = 2, unit = "Bytes", missing = "missing"
      description = "Freeable memory below 256 MiB for 10 minutes. Inspect connections and queries."
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "rds" {
  for_each            = local.alarms
  alarm_name          = "${var.name}-infra-rds-${each.key}"
  alarm_description   = each.value.description
  namespace           = "AWS/RDS"
  metric_name         = each.value.metric
  statistic           = each.value.statistic
  unit                = each.value.unit
  comparison_operator = each.value.operator
  threshold           = each.value.threshold
  period              = each.value.period
  evaluation_periods  = each.value.periods
  datapoints_to_alarm = each.value.periods
  dimensions          = { DBInstanceIdentifier = var.db_instance_identifier }
  treat_missing_data  = each.value.missing
  alarm_actions       = [aws_sns_topic.this.arn]
  ok_actions          = [aws_sns_topic.this.arn]
  depends_on          = [aws_sns_topic_policy.this]
}
