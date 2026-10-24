mock_provider "aws" {}

run "tokyo_only_notifications" {
  command = plan
  module { source = "../modules/cost-budget" }
  variables {
    name               = "test-team"
    monthly_budget_usd = 200
    email_recipients   = ["recipient@example.invalid"]
  }
  assert {
    condition = (
      length(aws_budgets_budget.tokyo) == 3 && alltrue([for b in aws_budgets_budget.tokyo :
        one(b.cost_filter).name == "Region" && toset(one(b.cost_filter).values) == toset(["ap-northeast-1"]) &&
        b.budget_type == "COST" && b.time_unit == "MONTHLY" &&
        b.limit_unit == "USD" && b.limit_amount == "200"
      ])
    )
    error_message = "The budget must only cover Tokyo at the agreed monthly USD threshold."
  }
  assert {
    condition = (
      alltrue([for b in aws_budgets_budget.tokyo : length(b.notification) <= 5]) &&
      toset(flatten([for b in aws_budgets_budget.tokyo : [for n in b.notification : "${n.notification_type}:${n.threshold}"]])) == toset(concat([for n in range(10, 101, 10) : "ACTUAL:${n}"], ["FORECASTED:100"])) &&
      alltrue(flatten([for b in aws_budgets_budget.tokyo : [for n in b.notification : n.comparison_operator == "GREATER_THAN" && n.threshold_type == "PERCENTAGE" && n.subscriber_email_addresses == toset(["recipient@example.invalid"])]])) &&
      alltrue([for b in aws_budgets_budget.tokyo : !one(b.cost_types).include_credit && !one(b.cost_types).include_refund && !one(b.cost_types).include_tax])
    )
    error_message = "Keep eleven notifications under AWS per-budget limits and exclude credits/refunds/tax."
  }
}

run "reject_zero_budget" {
  command = plan
  module { source = "../modules/cost-budget" }
  variables {
    name               = "test-team"
    monthly_budget_usd = 0
    email_recipients   = ["recipient@example.invalid"]
  }
  expect_failures = [var.monthly_budget_usd]
}

run "reject_empty_recipients" {
  command = plan
  module { source = "../modules/cost-budget" }
  variables {
    name               = "test-team"
    monthly_budget_usd = 200
    email_recipients   = []
  }
  expect_failures = [var.email_recipients]
}

run "reject_invalid_recipient" {
  command = plan
  module { source = "../modules/cost-budget" }
  variables {
    name               = "test-team"
    monthly_budget_usd = 200
    email_recipients   = ["invalid"]
  }
  expect_failures = [var.email_recipients]
}
