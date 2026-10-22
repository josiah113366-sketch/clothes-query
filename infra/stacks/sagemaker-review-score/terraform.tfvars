# 팀이 같이 보는 기본값. 계정 ID·state 버킷은 deployment.auto.tfvars.json(공유, 추적), 개인 값은 deployment.local.tfvars.json(Git 제외)에 둔다.
use_vpc             = true
review_input_prefix = "silver/reviews"
work_prefix         = "review-score"
instance_type       = "ml.g4dn.xlarge"
max_runtime_seconds = 3600
output_prefix       = "silver/review_aspect_scores"
error_prefix        = "silver/review_aspect_scores_error"
model_version       = "2.4b_score_s2c"
