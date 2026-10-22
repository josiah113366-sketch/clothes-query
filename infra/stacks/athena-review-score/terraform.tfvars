# 팀이 같이 보는 기본값. 계정 ID·state 버킷은 deployment.auto.tfvars.json(공유, 추적), 개인 값은 deployment.local.tfvars.json(Git 제외)에 둔다.
staging_prefix       = "staging/review-score"
table_prefix         = "silver/review_aspect_scores_iceberg"
results_prefix       = "athena-results/review-score"
database_name        = "clothes_query_dev_review_score"
table_name           = "review_aspect_scores"
staging_table_name   = "staging_review_aspect_scores"
bytes_scanned_cutoff = 10737418240
