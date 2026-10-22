"""ECS 배포·운영 스크립트(deploy/*.py) 테스트 — 가짜 AWS(moto), 실제 AWS 호출 없음 (2026-10-18 sim/review-ecs)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
sys.path.insert(0, str(DEPLOY))

import aws_common
import check_access
import onoff
import run_incident
import run_rds
import secret
import status
import switch

import deploy

REGION = "ap-northeast-1"
BUCKET = "test-lake"


@pytest.fixture
def aws(monkeypatch):
    """가짜 AWS 에 Terraform 이 만들 것(설정 SSM, 클러스터, 스케줄, secret, 로그, 버킷)을 흉내 내 둔다."""
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
    }.items():
        monkeypatch.setenv(k, v)
    with moto.mock_aws():
        sess = boto3.Session(region_name=REGION)
        ecs = sess.client("ecs")
        cluster = ecs.create_cluster(clusterName="rsim")["cluster"]
        s3 = sess.client("s3")
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        secret_arn = sess.client("secretsmanager").create_secret(Name="rsim/bedrock")["ARN"]
        orders_db_arn = sess.client("secretsmanager").create_secret(Name="rsim/orders-db")["ARN"]
        logs = sess.client("logs")
        logs.create_log_group(logGroupName="/ecs/rsim")
        logs.create_log_group(logGroupName="/aws/events/rsim")
        iam = sess.client("iam")
        role = iam.create_role(RoleName="sch", AssumeRolePolicyDocument="{}")["Role"]["Arn"]
        cfg = {
            "region": REGION,
            "cluster": "rsim",
            "cluster_arn": cluster["clusterArn"],
            "task_family": "rsim",
            "container_name": "review-simulator",
            "cpu": "512",
            "memory": "1024",
            "ecr_repository_url": "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/cq/review-simulator",
            "execution_role_arn": role,
            "task_role_arn": role,
            "secret_arn": secret_arn,
            "orders_db_secret_arn": orders_db_arn,
            "subnets": ["subnet-1"],
            "security_groups": ["sg-1"],
            "app_log_group": "/ecs/rsim",
            "events_log_group": "/aws/events/rsim",
            "schedule_name": "rsim-daily",
            "schedule_group": "default",
            "lake_root": f"s3://{BUCKET}/bronze",
            "input_root": f"s3://{BUCKET}/sim-input/review-simulator",
            "dashboard": "rsim",
        }
        sess.client("ssm").put_parameter(
            Name=aws_common.CONFIG_PARAMETER, Type="String", Value=json.dumps(cfg)
        )
        sess.client("scheduler").create_schedule(
            Name="rsim-daily",
            ScheduleExpression="cron(30 0 * * ? *)",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="DISABLED",
            Target={
                "Arn": cluster["clusterArn"],
                "RoleArn": role,
                "EcsParameters": {"TaskDefinitionArn": "arn:aws:ecs:x:1:task-definition/rsim"},
            },
        )
        yield sess, cfg


def _register(sess, cfg, tag="0.2.0-abc1234"):
    return aws_common.register_revision(
        sess.client("ecs"), cfg, image=f"{cfg['ecr_repository_url']}:{tag}"
    )


def test_first_revision_has_defaults_and_secret(aws):
    sess, cfg = aws
    td = _register(sess, cfg)
    env = aws_common.env_of(td)
    assert env["LAKE_ROOT"] == f"s3://{BUCKET}/bronze"
    assert env["REVIEW_RATE"] == "0.1"  # 처음에는 low
    assert env["EXAMPLES_VERSION"] == "ex-v1"
    c = td["containerDefinitions"][0]
    assert c["secrets"] == [{"name": "AWS_BEARER_TOKEN_BEDROCK", "valueFrom": cfg["secret_arn"]}]
    assert c["entryPoint"] == ["/bin/sh", "/app/deploy/entrypoint.sh"]
    assert "AWS_BEARER_TOKEN_BEDROCK" not in env  # 키 값은 환경변수 평문으로 안 들어간다
    assert env["ORDERS_SOURCE"] == "fake"  # 처음에는 가짜 주문 (RDS 접속 secret 은 안 넣는다)


def test_switch_orders_to_rds_needs_secret_then_injects_it(aws, capsys):
    sess, cfg = aws
    _register(sess, cfg)
    # 접속 주소 secret 이 비어 있으면 rds 로 못 바꾼다 (빈 secret 을 넣으면 태스크가 시작부터 실패하므로)
    with pytest.raises(SystemExit):
        switch.main(["--orders", "rds"])
    # localhost 주소(로컬 port-forward)는 ECS 에서 못 쓰므로 거절
    with pytest.raises(SystemExit):
        secret.check_db_url("postgresql://ro:pw@localhost:5432/clothes")
    sess.client("secretsmanager").put_secret_value(
        SecretId=cfg["orders_db_secret_arn"], SecretString="postgresql://ro:pw@db.internal:5432/x"
    )
    switch.main(["--orders", "rds"])
    td = aws_common.latest_task_definition(sess.client("ecs"), "rsim")
    assert aws_common.env_of(td)["ORDERS_SOURCE"] == "rds"
    assert aws_common.env_of(td)["REVIEW_RATE"] == "0.1"  # 비율은 그대로
    assert {"name": "ORDERS_DATABASE_URL", "valueFrom": cfg["orders_db_secret_arn"]} in td[
        "containerDefinitions"
    ][0]["secrets"]
    assert "ORDERS_DATABASE_URL" not in aws_common.env_of(td)  # 값은 평문 환경변수로 안 들어간다
    # 다시 fake 로 돌리면 secret 주입도 빠진다
    switch.main(["--orders", "fake"])
    td = aws_common.latest_task_definition(sess.client("ecs"), "rsim")
    assert [x["name"] for x in td["containerDefinitions"][0]["secrets"]] == [
        "AWS_BEARER_TOKEN_BEDROCK"
    ]
    with pytest.raises(SystemExit):
        switch.main(["high", "--orders", "rds"])  # 비율과 같이 바꾸지 않는다


def test_switch_keeps_image_and_changes_rate(aws, capsys):
    sess, cfg = aws
    _register(sess, cfg)
    switch.main(["high"])
    td = aws_common.latest_task_definition(sess.client("ecs"), "rsim")
    assert aws_common.env_of(td)["REVIEW_RATE"] == "1"
    assert aws_common.image_tag_of(td) == "0.2.0-abc1234"
    assert "하루 약 1,000건" in capsys.readouterr().out
    # 이후 deploy(새 이미지)는 바꾼 비율을 이어받는다
    td = _register(sess, cfg, tag="0.2.0-def5678")
    assert aws_common.env_of(td)["REVIEW_RATE"] == "1"


def test_switch_rejects_bad_input():
    with pytest.raises(SystemExit):
        switch.parse_rate(None, None)
    with pytest.raises(SystemExit):
        switch.parse_rate("low", 0.2)
    with pytest.raises(SystemExit):
        switch.parse_rate(None, 1.5)
    assert switch.parse_rate("normal", None) == 0.5


def test_onoff_on_points_schedule_to_latest_and_off_disables(aws):
    sess, cfg = aws
    td = _register(sess, cfg)
    onoff.main(["on"])
    sch = aws_common.get_schedule(sess.client("scheduler"), cfg)
    assert sch["State"] == "ENABLED"
    assert sch["Target"]["EcsParameters"]["TaskDefinitionArn"] == td["taskDefinitionArn"]
    # 켜진 상태에서 새 리비전을 등록하면 스케줄도 따라간다
    switch.main(["normal"])
    new = aws_common.latest_task_definition(sess.client("ecs"), "rsim")
    sch = aws_common.get_schedule(sess.client("scheduler"), cfg)
    assert sch["Target"]["EcsParameters"]["TaskDefinitionArn"] == new["taskDefinitionArn"]
    onoff.main(["off"])
    assert aws_common.get_schedule(sess.client("scheduler"), cfg)["State"] == "DISABLED"


def test_run_task_overrides(aws, monkeypatch):
    """한 번 실행은 이번 실행에만 env/command 를 덮어쓴다 (run_task 호출 인자 확인)."""
    sess, cfg = aws
    _register(sess, cfg)
    calls = {}

    class FakeEcs:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

        def run_task(self, **kwargs):
            calls.update(kwargs)
            return {"tasks": [{"taskArn": "arn:aws:ecs:x:1:task/rsim/abc"}], "failures": []}

    ecs = FakeEcs(sess.client("ecs"))
    arn = aws_common.run_task(ecs, cfg, env={"RUN_DATE": "2026-10-17", "LLM": "fake"})
    assert arn.endswith("/abc")
    override = calls["overrides"]["containerOverrides"][0]
    assert override["environment"] == [
        {"name": "RUN_DATE", "value": "2026-10-17"},
        {"name": "LLM", "value": "fake"},
    ]
    net = calls["networkConfiguration"]["awsvpcConfiguration"]
    assert net["assignPublicIp"] == "DISABLED" and net["subnets"] == ["subnet-1"]
    aws_common.run_task(ecs, cfg, command=["inject", "--file", "s3://b/k.csv"])
    assert calls["overrides"]["containerOverrides"][0]["command"] == [
        "inject",
        "--file",
        "s3://b/k.csv",
    ]


def test_run_incident_builds_existing_format():
    item = run_incident.build_incident(
        day="2026-10-17", aspect="배송", sentiment="부정", share=0.4, category="패션슈즈"
    )
    assert item["start"] == "2026-10-17T00:00:00+00:00"
    assert item["end"] == "2026-10-18T00:00:00+00:00"
    assert item["category"] == "패션슈즈" and "product_id" not in item
    # 시뮬레이터의 기존 incidents 읽기 코드가 그대로 읽는다
    from rsim.review.scenario import Incident

    inc = Incident(**{**item, "start": None, "end": None})
    assert inc.aspect == "배송"
    with pytest.raises(SystemExit):
        run_incident.build_incident(
            day="2026-10-17", aspect="없는속성", sentiment="부정", share=0.4, product_id="W-0001"
        )
    with pytest.raises(SystemExit):
        run_incident.build_incident(day="2026-10-17", aspect="배송", sentiment="부정", share=0.4)


def test_upload_input_and_incidents_from_s3(aws, monkeypatch):
    """run_incident 가 올린 JSON 을 시뮬레이터가 INCIDENTS_PATH=s3://… 로 읽는다."""
    sess, cfg = aws
    item = run_incident.build_incident(
        day="2026-10-17", aspect="사이즈·핏", sentiment="긍정", share=0.8, product_id="W-0003"
    )
    uri = aws_common.upload_input(
        sess, cfg, "incidents", "a.json", json.dumps([item], ensure_ascii=False).encode()
    )
    assert uri == f"s3://{BUCKET}/sim-input/review-simulator/incidents/a.json"
    from rsim.common.config import load_settings
    from rsim.review.scenario import load_incidents

    monkeypatch.setenv("INCIDENTS_PATH", uri)
    path = load_settings().incidents_path
    assert path == uri  # s3 경로는 Path 로 바뀌지 않는다
    incs = load_incidents(path)
    assert incs[0].product_id == "W-0003" and incs[0].sentiment == "긍정"


def test_secret_put_and_check(aws, tmp_path):
    sess, cfg = aws
    sm = sess.client("secretsmanager")
    assert not secret.has_value(sm, cfg["secret_arn"])
    env = tmp_path / ".env"
    env.write_text("AWS_REGION=x\nAWS_BEARER_TOKEN_BEDROCK=abc123\n", encoding="utf-8")
    assert secret.read_env_file(env) == "abc123"
    secret.put_key(sm, cfg["secret_arn"], "abc123")
    assert secret.has_value(sm, cfg["secret_arn"])
    with pytest.raises(SystemExit):
        secret.put_key(sm, cfg["secret_arn"], "")


def test_status_parses_run_logs_and_partition(aws, capsys):
    sess, cfg = aws
    events = [
        {
            "logStreamName": "rsim/a",
            "timestamp": 2000,
            "message": "INFO x: 끝: 전송 95건, 건너뜀 5건, 모델 호출 40회, 입력 토큰 100000, 출력 토큰 20000",
        },
        {
            "logStreamName": "rsim/a",
            "timestamp": 2001,
            "message": "INFO x: 검수 호출 20회, 입력 토큰 50000, 출력 토큰 10000",
        },
        {
            "logStreamName": "rsim/b",
            "timestamp": 1000,
            "message": "INFO x: 진행: 전송 5건, 건너뜀 0건",
        },
    ]
    runs = status.parse_runs(events)
    assert len(runs) == 1 and runs[0]["sent"] == 95
    assert runs[0]["in"] == 150000 and runs[0]["out"] == 30000
    assert status.price_of("google.gemma-3-12b-it") == (0.11, 0.35)
    s3 = sess.client("s3")
    for day in ("year=2026/month=10/day=16", "year=2026/month=10/day=17"):
        s3.put_object(Bucket=BUCKET, Key=f"bronze/reviews/{day}/part-00000.jsonl", Body=b"{}")
    assert status.last_partition(s3, cfg["lake_root"]) == "year=2026/month=10/day=17"
    _register(sess, cfg)
    status.main([])
    out = capsys.readouterr().out
    assert "[스케줄] DISABLED" in out and "REVIEW_RATE=0.1" in out


def test_deploy_tag_and_version():
    assert deploy.read_version().count(".") == 2
    assert deploy.make_tag("0.2.0", "abc1234", False) == "0.2.0-abc1234"
    assert deploy.make_tag("0.2.0", "abc1234", True).startswith("0.2.0-abc1234-dirty")


def test_check_access_action_list_is_unique():
    actions = [a for _, a in check_access.ACTIONS]
    assert len(actions) == len(set(actions))
    assert all(":" in a for a in actions)


@pytest.mark.skipif(
    shutil.which("sh") is None or os.name == "nt", reason="sh 가 없는 환경 (Windows)"
)
def test_entrypoint_runs_same_rsim_commands(tmp_path):
    """컨테이너 진입점이 로컬과 같은 rsim 명령을 부르는지 (가짜 rsim 으로 인자만 기록)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.txt"
    fake = bindir / "rsim"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n', encoding="utf-8")
    fake.chmod(0o755)
    py = bindir / "python"
    py.write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n', encoding="utf-8")
    py.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "RUN_DATE": "2026-10-17",
        "ORDERS_FAKE_START": "2026-10-01T00:00:00+00:00",
    }
    script = DEPLOY / "container/entrypoint.sh"
    subprocess.run(["sh", str(script)], env=env, check=True, capture_output=True)
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls == [
        "orders-fake --start 2026-10-01T00:00:00+00:00 --days 17 --per-day 1000 --seed 42",
        "run --source orders --sink lake --llm bedrock --date 2026-10-17",
    ]
    log.unlink()
    # ORDERS_SOURCE=rds 면 가짜 주문 없이 RDS 주문으로 바로 리뷰
    subprocess.run(
        ["sh", str(script)], env={**env, "ORDERS_SOURCE": "rds"}, check=True, capture_output=True
    )
    assert log.read_text(encoding="utf-8").splitlines() == [
        "run --source rds --sink lake --llm bedrock --date 2026-10-17"
    ]
    log.unlink()
    subprocess.run(["sh", str(script), "inject", "--file", "s3://b/k.csv"], env=env, check=True)
    assert log.read_text(encoding="utf-8").strip() == "inject --file s3://b/k.csv"


def test_run_rds_checks_secret_switches_and_runs_bedrock(aws, monkeypatch, capsys):
    """run_rds.py: secret 이 비어 있으면 멈추고, 있으면 주문 입력을 rds 로 맞춘 뒤 Bedrock 으로 한 번 실행한다."""
    sess, cfg = aws
    _register(sess, cfg)
    with pytest.raises(SystemExit):
        run_rds.main(["--yes", "--date", "2026-10-20"])
    sess.client("secretsmanager").put_secret_value(
        SecretId=cfg["orders_db_secret_arn"],
        SecretString="postgresql://ro:pw@db.internal:5432/postgres",
    )
    calls = {}

    def fake_run_task(ecs, cfg_, *, env=None, command=None, started_by=""):
        calls.update(env=env, started_by=started_by)
        return "arn:aws:ecs:x:1:task/rsim/abc"

    monkeypatch.setattr(run_rds, "run_task", fake_run_task)
    # 확인에 n 을 누르면 실행하지 않는다 (rds 전환은 남는다)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    run_rds.main(["--date", "2026-10-20"])
    assert not calls
    td = aws_common.latest_task_definition(sess.client("ecs"), "rsim")
    assert aws_common.env_of(td)["ORDERS_SOURCE"] == "rds"
    rev = td["revision"]
    run_rds.main(["--yes", "--date", "2026-10-20"])
    assert calls["env"] == {
        "RUN_DATE": "2026-10-20",
        "LLM": "bedrock",
    }  # 가짜 문장이 아니라 실제 생성
    # 이미 rds 면 새 리비전을 또 만들지 않는다
    assert aws_common.latest_task_definition(sess.client("ecs"), "rsim")["revision"] == rev
    with pytest.raises(SystemExit):
        run_rds.main(["--yes", "--date", "20261020"])
