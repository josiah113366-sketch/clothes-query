resource "aws_iam_role_policy" "investigation_bedrock" {
  count = length(var.investigation_bedrock_profiles) > 0 ? 1 : 0
  name  = "confirmed-investigation-inference-profiles"
  role  = aws_iam_role.this["investigation"].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = flatten([for profile in values(var.investigation_bedrock_profiles) : [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:GetInferenceProfile"]
        Resource = [profile.profile_arn]
      },
      {
        Effect    = "Allow"
        Action    = ["bedrock:InvokeModel"]
        Resource  = sort(tolist(profile.model_arns))
        Condition = { StringEquals = { "bedrock:InferenceProfileArn" = profile.profile_arn } }
      }
    ]])
  })
}
