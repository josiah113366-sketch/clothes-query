# 팀이 같이 보는 비밀 아닌 값. 계정 ID·state 버킷·이메일은 deployment.local.tfvars(Git 제외)에 둔다.
use_vpc             = true
review_input_prefix = "bronze/reviews"
work_prefix         = "review-score"
instance_type       = "ml.g4dn.xlarge"
max_runtime_seconds = 3600
output_prefix       = "silver/review-score/output"
error_prefix        = "silver/review-score/error"
