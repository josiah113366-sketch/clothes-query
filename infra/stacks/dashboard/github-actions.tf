# GitHub Actions 가 대시보드 이미지를 ECR 에 올릴 때 쓰는 역할 (.github/workflows/dashboard-deploy.yml).
# 액세스 키를 GitHub 에 저장하지 않고, Actions 가 발급하는 OIDC 토큰으로 이 역할을 잠깐(최대 1시간) 받는다.
#
# 허용 범위
#   - 누가: var.github_repository 저장소의 main 브랜치에서 돈 워크플로만 (PR·다른 브랜치·포크는 거부)
#   - 무엇을: 대시보드 ECR 저장소 하나에 이미지 push/조회만. EKS·S3·Athena 등 다른 권한은 없다.
#     클러스터 반영은 Argo CD 가 Git 을 보고 하므로 CI 에는 쿠버네티스 권한을 주지 않는다.

# GitHub OIDC 공급자는 AWS 계정에 URL 당 하나만 만들 수 있다.
# 다른 스택(또는 사람)이 이미 만들었다면 create_github_oidc_provider=false 로 두고 기존 것을 읽어 쓴다.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"] # 워크플로가 토큰을 받을 때 쓰는 audience 와 같아야 한다
  # AWS 는 GitHub 공급자를 자체 신뢰 CA 로 검증하므로 thumbprint 를 따로 넣지 않는다 (aws provider 6.x 에서 선택값)
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "dashboard_ci_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # sub 는 "<접두어>:ref:refs/heads/<브랜치>". main 만 허용한다.
    # 이 저장소는 immutable subject 를 쓴다 (gh api repos/<저장소>/actions/oidc/customization/sub 의 use_immutable_subject=true).
    # 그래서 실제 토큰의 접두어는 "repo:<소유자>@<소유자ID>/<저장소>@<저장소ID>" 형태다 (var.github_sub_prefix).
    # 옛 형식(repo:<소유자>/<저장소>)도 같이 허용해, 설정이 기본으로 돌아가도 끊기지 않게 한다.
    # 다른 브랜치에서 시험 배포가 필요하면 여기에 그 브랜치를 잠깐 추가한다 (상시 허용하지 않는다)
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${var.github_sub_prefix}:ref:refs/heads/main",
        "repo:${var.github_repository}:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "dashboard_ci" {
  name                 = "${var.name}-dashboard-ci"
  description          = "GitHub Actions (main) pushes dashboard images to ECR"
  assume_role_policy   = data.aws_iam_policy_document.dashboard_ci_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "dashboard_ci_ecr" {
  # 로그인 토큰 발급은 저장소 단위로 좁힐 수 없는 API 라 * 이다 (토큰만으로는 아무 저장소에도 push 할 수 없다)
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  # 대시보드 저장소 하나에만 push·조회. 삭제(BatchDeleteImage)·정책 변경은 넣지 않는다
  statement {
    sid = "DashboardRepositoryPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
    ]
    resources = [aws_ecr_repository.dashboard.arn]
  }
}

resource "aws_iam_role_policy" "dashboard_ci_ecr" {
  name   = "dashboard-ecr-push"
  role   = aws_iam_role.dashboard_ci.id
  policy = data.aws_iam_policy_document.dashboard_ci_ecr.json
}
