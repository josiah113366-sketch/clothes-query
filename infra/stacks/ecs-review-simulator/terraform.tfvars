# Shared non-secret values. Account ID, state bucket and emails go in deployment.local.tfvars (ignored).
# 매일 00:00 KST (2026-10-23 lemin). 시간대는 모듈 변수 schedule_timezone(기본 Asia/Seoul)
schedule_expression = "cron(0 0 * * ? *)"
budget_limit_usd    = 10
