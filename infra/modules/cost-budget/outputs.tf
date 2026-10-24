output "budget_names" { value = { for key, budget in aws_budgets_budget.tokyo : key => budget.name } }
output "monthly_budget_usd" { value = var.monthly_budget_usd }
