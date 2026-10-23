mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_caller_identity" { defaults = { account_id = "000000000000" } }
}
variables {
  cluster_name        = "test-cluster"
  bucket_arn          = "arn:aws:s3:::test-gold-b-bucket"
  s3_endpoint_actions = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucket", "s3:GetBucketLocation"]
}
run "no_model_selected_no_permission" {
  command = plan
  module { source = "../modules/gold-b-access" }
  assert {
    condition     = length(aws_iam_role_policy.investigation_bedrock) == 0
    error_message = "No model invocation permission may exist before model selection."
  }
}
run "models_only_through_selected_profile" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables {
    investigation_bedrock_profiles = {
      haiku = {
        profile_arn = "arn:aws:bedrock:ap-northeast-1:000000000000:inference-profile/jp.anthropic.claude-haiku-4-5-20251001-v1:0"
        model_arns  = ["arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0", "arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"]
      }
    }
  }
  assert {
    condition = (
      aws_iam_role_policy.investigation_bedrock[0].role == aws_iam_role.this["investigation"].name &&
      jsondecode(aws_iam_role_policy.investigation_bedrock[0].policy).Statement[1].Condition.StringEquals["bedrock:InferenceProfileArn"] == var.investigation_bedrock_profiles.haiku.profile_arn &&
      length(jsondecode(aws_iam_role_policy.investigation_bedrock[0].policy).Statement[1].Resource) == 2
    )
    error_message = "Destination model access must be tied to the selected profile on the investigation role only."
  }
}
run "reject_global_or_wildcard_models" {
  command = plan
  module { source = "../modules/gold-b-access" }
  variables {
    investigation_bedrock_profiles = {
      broad = { profile_arn = "arn:aws:bedrock:ap-northeast-1:000000000000:inference-profile/global.example", model_arns = ["arn:aws:bedrock:*::foundation-model/*"] }
    }
  }
  expect_failures = [var.investigation_bedrock_profiles]
}
