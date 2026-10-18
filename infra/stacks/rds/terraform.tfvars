# Non-secret shared defaults only. Required deployment inputs go in an ignored local tfvars file.
aws_region     = "ap-northeast-1"
engine_version = "16.15"

# Approved initial Single-AZ sizing; storage autoscaling does not shrink volumes.
instance_class        = "db.t4g.small"
allocated_storage     = 20
max_allocated_storage = 100
