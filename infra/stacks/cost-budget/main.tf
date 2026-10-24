module "cost_budget" {
  source             = "../../modules/cost-budget"
  name               = "clothes-query-dev"
  monthly_budget_usd = var.monthly_budget_usd
  email_recipients   = var.email_recipients
}
