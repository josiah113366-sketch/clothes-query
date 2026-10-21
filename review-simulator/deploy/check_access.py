"""지금 로그인한 AWS 계정에 ECS 배포·운영 권한이 있는지 읽기 전용으로 확인한다 (2026-10-18 sim/review-ecs).

    python deploy/check_access.py

아무것도 만들거나 바꾸지 않는다. 두 단계로 본다.
  1. IAM 정책 시뮬레이터(iam:SimulatePrincipalPolicy): 각 작업이 허용되는지 정책만 보고 판정
     (조직 SCP·리소스 정책까지 완전히 반영하지는 않으므로 '허용'이어도 apply 때 막힐 수 있다)
  2. 시뮬레이터를 못 쓰면: 서비스별 목록 조회(List/Describe)를 한 번씩 불러 읽기 권한만 확인
결과의 '거부' 항목은 계정 관리자(재영)에게 권한을 요청할 목록이다.
"""

from __future__ import annotations

import argparse

from aws_common import session
from botocore.exceptions import BotoCoreError, ClientError

# (구분, 작업) — Terraform apply(infra/stacks/ecs-review-simulator)와 deploy/*.py 가 쓰는 작업
ACTIONS: list[tuple[str, str]] = [
    ("Terraform state", "s3:GetObject"),
    ("Terraform state", "s3:PutObject"),
    ("Terraform state", "s3:ListBucket"),
    ("ECR", "ecr:CreateRepository"),
    ("ECR", "ecr:PutLifecyclePolicy"),
    ("ECR", "ecr:GetAuthorizationToken"),
    ("ECR", "ecr:InitiateLayerUpload"),
    ("ECR", "ecr:PutImage"),
    ("ECR", "ecr:DescribeImages"),
    ("ECS", "ecs:CreateCluster"),
    ("ECS", "ecs:RegisterTaskDefinition"),
    ("ECS", "ecs:DescribeTaskDefinition"),
    ("ECS", "ecs:RunTask"),
    ("ECS", "ecs:StopTask"),
    ("ECS", "ecs:ListTasks"),
    ("ECS", "ecs:TagResource"),
    ("EC2 (보안 그룹)", "ec2:CreateSecurityGroup"),
    ("EC2 (보안 그룹)", "ec2:AuthorizeSecurityGroupEgress"),
    ("EC2 (보안 그룹)", "ec2:DescribeSecurityGroups"),
    # RDS(5432) 나가는 규칙을 VPC 주소 범위로 열 때 VPC 를 조회한다 (2026-10-21)
    ("EC2 (보안 그룹)", "ec2:DescribeVpcs"),
    ("IAM 역할", "iam:CreateRole"),
    ("IAM 역할", "iam:PutRolePolicy"),
    ("IAM 역할", "iam:AttachRolePolicy"),
    ("IAM 역할", "iam:PassRole"),
    ("Secrets Manager", "secretsmanager:CreateSecret"),
    ("Secrets Manager", "secretsmanager:PutSecretValue"),
    ("Secrets Manager", "secretsmanager:ListSecretVersionIds"),
    ("EventBridge Scheduler", "scheduler:CreateSchedule"),
    ("EventBridge Scheduler", "scheduler:GetSchedule"),
    ("EventBridge Scheduler", "scheduler:UpdateSchedule"),
    ("EventBridge (종료 기록)", "events:PutRule"),
    ("EventBridge (종료 기록)", "events:PutTargets"),
    ("CloudWatch Logs", "logs:CreateLogGroup"),
    ("CloudWatch Logs", "logs:PutRetentionPolicy"),
    ("CloudWatch Logs", "logs:PutMetricFilter"),
    ("CloudWatch Logs", "logs:PutResourcePolicy"),
    ("CloudWatch Logs", "logs:FilterLogEvents"),
    ("CloudWatch", "cloudwatch:PutDashboard"),
    ("CloudWatch", "cloudwatch:PutMetricAlarm"),
    ("SNS (선택: 알림 메일)", "sns:CreateTopic"),
    ("SNS (선택: 알림 메일)", "sns:Subscribe"),
    ("Budgets (선택: 예산 메일)", "budgets:ModifyBudget"),
    ("SSM 설정", "ssm:PutParameter"),
    ("SSM 설정", "ssm:GetParameter"),
    ("Cost Explorer (status --cost)", "ce:GetCostAndUsage"),
]

# 시뮬레이터를 못 쓸 때 부를 읽기 전용 호출 (서비스, 메서드, 인자)
PROBES = [
    ("ecr", "describe_repositories", {"maxResults": 1}),
    ("ecs", "list_clusters", {"maxResults": 1}),
    ("ec2", "describe_security_groups", {"MaxResults": 5}),
    ("iam", "list_roles", {"MaxItems": 1}),
    ("secretsmanager", "list_secrets", {"MaxResults": 1}),
    ("scheduler", "list_schedules", {"MaxResults": 1}),
    ("events", "list_rules", {"Limit": 1}),
    ("logs", "describe_log_groups", {"limit": 1}),
    ("cloudwatch", "list_dashboards", {}),
    ("ssm", "describe_parameters", {"MaxResults": 1}),
]


def principal_arn(sess) -> tuple[str, str]:
    """(호출자 ARN, 정책 시뮬레이터에 줄 IAM ARN). assumed-role 이면 역할 ARN 으로 바꾼다."""
    arn = sess.client("sts").get_caller_identity()["Arn"]
    if ":assumed-role/" not in arn:
        return arn, arn
    role_name = arn.split(":assumed-role/", 1)[1].split("/", 1)[0]
    try:
        # SSO 역할은 경로(/aws-reserved/...)가 있어서 이름만으로 ARN 을 만들면 틀린다
        return arn, sess.client("iam").get_role(RoleName=role_name)["Role"]["Arn"]
    except (BotoCoreError, ClientError):
        account = arn.split(":")[4]
        return arn, f"arn:aws:iam::{account}:role/{role_name}"


def simulate(iam, source_arn: str, actions: list[str]) -> dict[str, str]:
    """작업별 판정 (allowed / implicitDeny / explicitDeny). 리소스는 * 로 본다."""
    out = {}
    for i in range(0, len(actions), 20):  # 한 번에 너무 많이 보내지 않게 나눈다
        resp = iam.simulate_principal_policy(
            PolicySourceArn=source_arn, ActionNames=actions[i : i + 20]
        )
        for r in resp["EvaluationResults"]:
            out[r["EvalActionName"]] = r["EvalDecision"]
    return out


def probe(sess) -> list[tuple[str, str]]:
    results = []
    for service, method, kwargs in PROBES:
        try:
            getattr(sess.client(service), method)(**kwargs)
            results.append((f"{service}:{method}", "읽기 가능"))
        except (BotoCoreError, ClientError) as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            results.append((f"{service}:{method}", f"실패 ({code})"))
    return results


LABELS = {"allowed": "허용", "implicitDeny": "거부(정책 없음)", "explicitDeny": "거부(명시적 거부)"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    caller, source = principal_arn(sess)
    # 계정 ID 는 화면에만 보이고 어디에도 저장하지 않는다
    print(f"로그인: {caller}")
    try:
        decisions = simulate(sess.client("iam"), source, [a for _, a in ACTIONS])
    except (BotoCoreError, ClientError) as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
        print(f"정책 시뮬레이터를 쓸 수 없어({code}) 읽기 조회로만 확인합니다.\n")
        for name, result in probe(sess):
            print(f"  {name:45s} {result}")
        print("\n읽기만 확인한 결과입니다. 만들기 권한은 terraform plan/apply 때 확인됩니다.")
        return

    denied = 0
    group = None
    for label, action in ACTIONS:
        if label != group:
            print(f"\n[{label}]")
            group = label
        d = decisions.get(action, "?")
        denied += d != "allowed"
        print(f"  {action:42s} {LABELS.get(d, d)}")
    print(
        f"\n거부 {denied}개 / 전체 {len(ACTIONS)}개"
        + (" → 관리자에게 요청할 목록" if denied else "")
    )


if __name__ == "__main__":
    main()
