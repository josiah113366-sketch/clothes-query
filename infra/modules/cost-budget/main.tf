locals {
  # AWS permits at most five notifications per budget. All three budgets
  # observe the same costs and limit; their limits must not be added together.
  notification_groups = {
    actual_10_50  = { type = "ACTUAL", thresholds = [10, 20, 30, 40, 50] }
    actual_60_100 = { type = "ACTUAL", thresholds = [60, 70, 80, 90, 100] }
    forecast_100  = { type = "FORECASTED", thresholds = [100] }
  }
}

resource "aws_budgets_budget" "tokyo" {
  for_each     = local.notification_groups
  name         = "${var.name}-tokyo-monthly-${replace(each.key, "_", "-")}"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "Region"
    values = ["ap-northeast-1"]
  }

  cost_types {
    include_credit = false
    include_refund = false
    include_tax    = false
    use_blended    = false
    use_amortized  = false
  }

  dynamic "notification" {
    for_each = toset(each.value.thresholds)
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = each.value.type
      subscriber_email_addresses = var.email_recipients
    }
  }
}
