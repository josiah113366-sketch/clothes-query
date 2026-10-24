output "topic_arn" { value = aws_sns_topic.this.arn }
output "alarm_names" { value = [for alarm in aws_cloudwatch_metric_alarm.rds : alarm.alarm_name] }
output "alertmanager_role_arn" { value = aws_iam_role.alertmanager.arn }
