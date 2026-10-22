"""배포·운영 스크립트 공통 부분 (2026-10-18 sim/review-ecs).

스크립트는 모두 review-simulator/ 폴더에서 `python deploy/<이름>.py ...` 로 실행한다(PowerShell 그대로).
AWS 자격 증명은 boto3 기본 방식(aws login / aws configure sso / 환경변수)을 쓴다. .env 의 키는 읽지 않는다.

리소스 이름·ARN 은 Terraform(infra/stacks/ecs-review-simulator)이 SSM 파라미터 하나에 JSON 으로 남긴다.
스크립트는 그 값만 읽으므로 Terraform 을 몰라도 되고, 공개 저장소에 계정 ID·버킷 이름을 적지 않아도 된다.

태스크 정의는 Terraform 이 아니라 스크립트가 관리한다(이미지 태그·실행 비율이 자주 바뀌어서).
    deploy.py  : 새 이미지로 새 리비전 등록 (다른 설정은 이전 리비전 그대로)
    switch.py  : REVIEW_RATE 또는 주문 입력(ORDERS_SOURCE: fake / rds)만 바꾼 새 리비전 등록
    onoff.py   : 스케줄을 최신 리비전으로 켜고 끄기, 한 번 실행
스케줄이 켜져 있으면 새 리비전을 등록할 때 스케줄도 그 리비전을 가리키게 바꾼다.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

# Terraform 모듈 기본값과 같아야 한다 (infra/modules/ecs-review-simulator variables.tf config_parameter_name)
CONFIG_PARAMETER = os.getenv(
    "RSIM_CONFIG_PARAMETER", "/clothes-query/dev/ecs-review-simulator/config"
)
DEFAULT_REGION = "ap-northeast-1"

# 실행 비율 단계 (switch.py). 하루 리뷰 수 ≈ ORDERS_PER_DAY(1000) x REVIEW_RATE
# 2026-10-18 lemin: 모드 switch = 리뷰 작성 비율. 목표 하루 1,000건 = high
RATE_PRESETS = {"low": 0.1, "normal": 0.5, "high": 1.0}

# 첫 배포 때 넣는 환경변수. 이후 배포는 이전 리비전 값을 그대로 이어받고, 여기 있는데 이전 리비전에 없는 이름만 추가한다.
# 값은 로컬 .env.example 기본값과 같다(기능 차이 없음). 바꾸려면 여기 또는 switch.py.
DEFAULT_ENV = {
    "BEDROCK_MODEL_ID": "google.gemma-3-12b-it",
    "EXAMPLES_VERSION": "ex-v1",
    "REVIEW_RATE": str(
        RATE_PRESETS["low"]
    ),  # 처음에는 하루 약 100건으로 시작 (비용 확인 후 switch.py high)
    # 주문을 어디서 읽을지 (2026-10-21). entrypoint.sh 가 이 값으로 명령을 고른다.
    #   fake : 가짜 주문을 만들고(rsim orders-fake) 그 주문에 리뷰 (예전 방식, 기본값 = 이미 배포한 리비전과 같은 동작)
    #   rds  : RDS orders 테이블을 읽어 리뷰 (rsim run --source rds). RDS 접속 secret 값과 RDS 쪽 허용이 먼저 있어야 한다
    # 바꾸기: python deploy/switch.py --orders rds
    "ORDERS_SOURCE": "fake",
    "ORDERS_PER_DAY": "1000",
    "ORDERS_FAKE_START": "2026-10-01T00:00:00+00:00",
    "ORDERS_SEED": "42",
    "LLM": "bedrock",
    # 정답 라벨 S3 저장은 차후 개선(2026-10-18 lemin). 컨테이너 안에만 쓰고 태스크가 끝나면 사라진다
    "LAKE_TRUTH_ROOT": "/tmp/review-truth",
}
SECRET_ENV_NAME = "AWS_BEARER_TOKEN_BEDROCK"
# RDS 접속 주소 환경변수 이름 (rsim 설정 orders_database_url 과 같은 이름)
ORDERS_DB_ENV_NAME = "ORDERS_DATABASE_URL"
ORDERS_SOURCES = ("fake", "rds")
TAGS = [
    {"key": "Project", "value": "clothes-query"},
    {"key": "Component", "value": "ecs-review-simulator"},
]


def session(region: str | None = None):
    """boto3 세션. .env 의 빈 AWS_PROFILE= 때문에 ProfileNotFound 가 나지 않게 지운다(sinks.s3_client 와 같은 처리)."""
    try:
        import boto3
    except ImportError:
        raise SystemExit("boto3 가 필요합니다: pip install -e .") from None
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        if name in os.environ and not os.environ[name].strip():
            del os.environ[name]
    return boto3.Session(region_name=region or os.getenv("AWS_REGION") or DEFAULT_REGION)


def load_config(sess) -> dict:
    """Terraform 이 만든 SSM 파라미터(JSON)를 읽는다."""
    ssm = sess.client("ssm")
    try:
        value = ssm.get_parameter(Name=CONFIG_PARAMETER)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        raise SystemExit(
            f"설정 {CONFIG_PARAMETER} 이 없습니다. infra/stacks/ecs-review-simulator 를 먼저 apply 하세요."
        ) from None
    return json.loads(value)


# ---------------------------------------------------------------- 태스크 정의
def latest_task_definition(ecs, family: str) -> dict | None:
    """패밀리의 최신 ACTIVE 리비전. 아직 없으면 None (첫 deploy 전)."""
    try:
        resp = ecs.describe_task_definition(taskDefinition=family, include=["TAGS"])
    except ecs.exceptions.ClientException:
        return None
    return resp["taskDefinition"]


def env_of(td: dict) -> dict[str, str]:
    """태스크 정의 첫 컨테이너의 환경변수 dict."""
    return {e["name"]: e["value"] for e in td["containerDefinitions"][0].get("environment", [])}


def image_tag_of(td: dict) -> str:
    return td["containerDefinitions"][0]["image"].rsplit(":", 1)[-1]


def secrets_of(cfg: dict, env: dict[str, str]) -> list[dict]:
    """태스크에 넣을 secret 목록.

    - Bedrock API 키: 항상
    - RDS 접속 주소(ORDERS_DATABASE_URL): ORDERS_SOURCE=rds 일 때만.
      값이 비어 있는 secret 을 넣으면 태스크가 시작부터 실패하므로, 가짜 주문 모드에서는 넣지 않는다.
      예전 Terraform(설정에 orders_db_secret_arn 없음)으로 rds 를 고르면 여기서 멈춘다.
    """
    secrets = [{"name": SECRET_ENV_NAME, "valueFrom": cfg["secret_arn"]}]
    if env.get("ORDERS_SOURCE") == "rds":
        if not cfg.get("orders_db_secret_arn"):
            raise SystemExit(
                "설정에 orders_db_secret_arn 이 없습니다. infra/stacks/ecs-review-simulator 를 다시 apply 하세요."
            )
        secrets.append({"name": ORDERS_DB_ENV_NAME, "valueFrom": cfg["orders_db_secret_arn"]})
    return secrets


def container_definition(cfg: dict, image: str, env: dict[str, str]) -> dict:
    """컨테이너 정의. 진입점은 deploy/container/entrypoint.sh (인자 없으면 하루치 실행)."""
    return {
        "name": cfg["container_name"],
        "image": image,
        "essential": True,
        "entryPoint": ["/bin/sh", "/app/deploy/entrypoint.sh"],
        "environment": [{"name": k, "value": v} for k, v in sorted(env.items())],
        # 비밀값은 Secrets Manager 에서 태스크 시작 때 환경변수로 들어간다(로그·태스크 정의에 값이 안 남음)
        "secrets": secrets_of(cfg, env),
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": cfg["app_log_group"],
                "awslogs-region": cfg["region"],
                "awslogs-stream-prefix": "rsim",
            },
        },
    }


def register_revision(
    ecs, cfg: dict, *, image: str | None = None, env_updates: dict[str, str] | None = None
) -> dict:
    """새 리비전을 등록한다. image/env_updates 로 준 것만 바뀌고 나머지는 최신 리비전 값을 쓴다.

    첫 등록이면 image 가 꼭 있어야 하고 환경변수는 DEFAULT_ENV + 고정값(리전, 레이크 경로)이다.
    """
    base = latest_task_definition(ecs, cfg["task_family"])
    if base is None and image is None:
        raise SystemExit(
            "등록된 태스크 정의가 없습니다. 먼저 python deploy/deploy.py 로 배포하세요."
        )
    env = {**DEFAULT_ENV}
    if base is not None:
        env.update(env_of(base))
    # 리전·레이크 경로는 Terraform 값을 따른다(버킷이 바뀌면 다음 등록 때 같이 바뀜)
    env["AWS_REGION"] = cfg["region"]
    env["LAKE_ROOT"] = cfg["lake_root"]
    env.update(env_updates or {})
    td = ecs.register_task_definition(
        family=cfg["task_family"],
        taskRoleArn=cfg["task_role_arn"],
        executionRoleArn=cfg["execution_role_arn"],
        networkMode="awsvpc",
        requiresCompatibilities=["FARGATE"],
        cpu=str(cfg["cpu"]),
        memory=str(cfg["memory"]),
        runtimePlatform={"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        containerDefinitions=[
            container_definition(cfg, image or base["containerDefinitions"][0]["image"], env)
        ],
        tags=TAGS,
    )["taskDefinition"]
    return td


# ---------------------------------------------------------------- 스케줄
def get_schedule(scheduler, cfg: dict) -> dict:
    return scheduler.get_schedule(Name=cfg["schedule_name"], GroupName=cfg["schedule_group"])


def update_schedule(
    scheduler, cfg: dict, *, state: str | None = None, task_def_arn: str | None = None
):
    """스케줄의 상태(ENABLED/DISABLED)나 실행할 리비전을 바꾼다. UpdateSchedule 은 전체 값을 다시 줘야 한다."""
    cur = get_schedule(scheduler, cfg)
    target = cur["Target"]
    if task_def_arn:
        target["EcsParameters"]["TaskDefinitionArn"] = task_def_arn
    kwargs = {
        "Name": cur["Name"],
        "GroupName": cur["GroupName"],
        "ScheduleExpression": cur["ScheduleExpression"],
        "FlexibleTimeWindow": cur["FlexibleTimeWindow"],
        "Target": target,
        "State": state or cur["State"],
    }
    for key in ("ScheduleExpressionTimezone", "Description"):
        if cur.get(key):
            kwargs[key] = cur[key]
    scheduler.update_schedule(**kwargs)
    return kwargs


def follow_new_revision(sess, cfg: dict, td_arn: str) -> bool:
    """스케줄이 켜져 있으면 새 리비전을 실행하게 바꾼다. 꺼져 있으면 그대로 두고 켤 때(onoff on) 최신으로 맞춘다."""
    scheduler = sess.client("scheduler")
    if get_schedule(scheduler, cfg)["State"] != "ENABLED":
        return False
    update_schedule(scheduler, cfg, task_def_arn=td_arn)
    return True


# ---------------------------------------------------------------- 한 번 실행
def run_task(
    ecs,
    cfg: dict,
    *,
    env: dict[str, str] | None = None,
    command: list[str] | None = None,
    started_by: str = "rsim-script",
) -> str:
    """최신 리비전으로 태스크를 한 번 실행한다. env/command 는 이번 실행에만 덮어쓴다(태스크 정의는 그대로)."""
    td = latest_task_definition(ecs, cfg["task_family"])
    if td is None:
        raise SystemExit(
            "등록된 태스크 정의가 없습니다. 먼저 python deploy/deploy.py 로 배포하세요."
        )
    override: dict = {"name": cfg["container_name"]}
    if env:
        override["environment"] = [{"name": k, "value": v} for k, v in env.items()]
    if command:
        override["command"] = command
    resp = ecs.run_task(
        cluster=cfg["cluster"],
        taskDefinition=td["taskDefinitionArn"],
        launchType="FARGATE",
        count=1,
        startedBy=started_by[:36],
        propagateTags="TASK_DEFINITION",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": cfg["subnets"],
                "securityGroups": cfg["security_groups"],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={"containerOverrides": [override]},
    )
    if resp.get("failures"):
        raise SystemExit(f"태스크를 시작하지 못했습니다: {resp['failures']}")
    return resp["tasks"][0]["taskArn"]


def yesterday_utc() -> str:
    """로컬 rsim run --source orders 기본 날짜와 같은 '어제(UTC)'."""
    return (datetime.now(UTC) - timedelta(days=1)).date().isoformat()


def split_s3(uri: str) -> tuple[str, str]:
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


def upload_input(sess, cfg: dict, sub: str, name: str, body: bytes) -> str:
    """입력 파일을 <input_root>/<sub>/<name> 에 올리고 s3:// 경로를 돌려준다 (태스크 역할이 읽을 수 있는 곳)."""
    bucket, prefix = split_s3(cfg["input_root"])
    key = f"{prefix.rstrip('/')}/{sub}/{name}"
    sess.client("s3").put_object(Bucket=bucket, Key=key, Body=body)
    return f"s3://{bucket}/{key}"


def log_tail_hint(cfg: dict, task_arn: str) -> str:
    """방금 시작한 태스크의 로그를 볼 명령."""
    task_id = task_arn.rsplit("/", 1)[-1]
    return (
        f"aws logs tail {cfg['app_log_group']} --log-stream-names "
        f"rsim/{cfg['container_name']}/{task_id} --follow"
    )
