"""ECS 리뷰 시뮬레이터 상태·비용을 한 화면에 보여 준다 (2026-10-18 sim/review-ecs, 관제).

    python deploy/status.py            # 스케줄, 실행 설정, 돌고 있는 태스크, 최근 실행, S3 마지막 날짜
    python deploy/status.py --cost     # + 이번 달 실제 청구액(Cost Explorer, 호출 1번에 $0.01)

같은 내용을 그래프로 보려면 CloudWatch 대시보드(이름은 Terraform output dashboard_name)를 연다.
Bedrock 추정 비용 = 로그의 토큰 수 x 단가(src/rsim/bench/prices.json). 실제 청구액과 조금 다를 수 있다.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aws_common import (
    env_of,
    get_schedule,
    image_tag_of,
    latest_task_definition,
    load_config,
    session,
    split_s3,
)
from botocore.exceptions import BotoCoreError, ClientError

PRICES = Path(__file__).resolve().parent.parent / "src/rsim/bench/prices.json"
# run.py 가 실행 끝에 남기는 두 줄. 문구를 바꾸면 여기와 Terraform 대시보드 쿼리를 같이 바꾼다
END_RE = re.compile(
    r"끝: 전송 (\d+)건, 건너뜀 (\d+)건, 모델 호출 (\d+)회, 입력 토큰 (\d+), 출력 토큰 (\d+)"
)
VERIFY_RE = re.compile(r"검수 호출 (\d+)회, 입력 토큰 (\d+), 출력 토큰 (\d+)")


def price_of(model_id: str) -> tuple[float, float] | None:
    """100만 토큰당 USD (입력, 출력). bench 와 같은 단가표를 쓴다."""
    prices = json.loads(PRICES.read_text(encoding="utf-8"))
    key = re.sub(r"^(jp|apac|global|us|eu)\.", "", model_id)
    p = prices.get(key)
    return (p["input"], p["output"]) if p else None


def parse_runs(events: list[dict]) -> list[dict]:
    """로그 이벤트 → 실행(로그 스트림)별 요약. 최신 순."""
    runs: dict[str, dict] = {}
    for e in events:
        r = runs.setdefault(
            e["logStreamName"], {"stream": e["logStreamName"], "time": 0, "in": 0, "out": 0}
        )
        r["time"] = max(r["time"], e["timestamp"])
        if m := END_RE.search(e["message"]):
            sent, skipped, _, gin, gout = map(int, m.groups())
            r.update(sent=sent, skipped=skipped)
            r["in"] += gin
            r["out"] += gout
        elif m := VERIFY_RE.search(e["message"]):
            _, vin, vout = map(int, m.groups())
            r["in"] += vin
            r["out"] += vout
    return sorted((r for r in runs.values() if "sent" in r), key=lambda r: -r["time"])


def recent_runs(logs, group: str, days: int = 7) -> list[dict]:
    start = int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)
    events, token = [], None
    while True:
        kwargs = {
            "logGroupName": group,
            "startTime": start,
            "filterPattern": '?"끝: 전송" ?"검수 호출"',
        }
        if token:
            kwargs["nextToken"] = token
        resp = logs.filter_log_events(**kwargs)
        events += resp.get("events", [])
        token = resp.get("nextToken")
        if not token or len(events) > 2000:
            return parse_runs(events)


def recent_stops(logs, group: str, days: int = 7, limit: int = 5) -> list[dict]:
    start = int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)
    events = logs.filter_log_events(logGroupName=group, startTime=start).get("events", [])
    out = []
    for e in sorted(events, key=lambda e: -e["timestamp"])[:limit]:
        d = json.loads(e["message"]).get("detail", {})
        c = (d.get("containers") or [{}])[0]
        out.append(
            {
                "time": e["timestamp"],
                "stop_code": d.get("stopCode", "-"),
                "exit_code": c.get("exitCode", "-"),
                "reason": d.get("stoppedReason", ""),
                "started_by": d.get("startedBy", ""),
            }
        )
    return out


def last_partition(s3, lake_root: str) -> str | None:
    """bronze_v2/reviews/ 의 마지막 날짜 파티션 (year=/month=/day= 를 차례로 가장 큰 값으로 내려간다)."""
    bucket, prefix = split_s3(lake_root)
    prefix = f"{prefix.rstrip('/')}/reviews/"
    for _ in ("year", "month", "day"):
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")
        subs = sorted(p["Prefix"] for p in resp.get("CommonPrefixes", []))
        if not subs:
            return None
        prefix = subs[-1]
    return prefix.split("/reviews/", 1)[1].rstrip("/")


def month_cost(ce) -> list[tuple[str, float]]:
    """이번 달 서비스별 청구액 중 시뮬레이터 관련(ECS·ECR·Bedrock·로그·Secrets). 계정 전체 값이라 다른 팀 사용분도 섞인다."""
    today = datetime.now(UTC).date()
    start = today.replace(day=1)
    end = today + timedelta(days=1)
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    keys = (
        "Bedrock",
        "Gemma",
        "Elastic Container",
        "EC2 Container Registry",
        "CloudWatch",
        "Secrets",
    )
    rows = []
    for g in resp["ResultsByTime"][0]["Groups"]:
        name = g["Keys"][0]
        if any(k in name for k in keys):
            rows.append((name, float(g["Metrics"]["UnblendedCost"]["Amount"])))
    return sorted(rows, key=lambda r: -r[1])


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%m-%d %H:%M UTC")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cost", action="store_true", help="이번 달 실제 청구액 (Cost Explorer, $0.01)"
    )
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    cfg = load_config(sess)
    ecs, logs = sess.client("ecs"), sess.client("logs")

    sch = get_schedule(sess.client("scheduler"), cfg)
    # 시간대는 스케줄에 저장된 값을 그대로 보여 준다 (2026-10-23 에 UTC → Asia/Seoul)
    tz = sch.get("ScheduleExpressionTimezone") or "UTC"
    print(f"[스케줄] {sch['State']} · {sch['ScheduleExpression']} {tz}")

    td = latest_task_definition(ecs, cfg["task_family"])
    model = "google.gemma-3-12b-it"
    if td is None:
        print("[태스크 정의] 없음 (python deploy/deploy.py 로 첫 배포)")
    else:
        env = env_of(td)
        model = env.get("BEDROCK_MODEL_ID", model)
        rate = float(env.get("REVIEW_RATE", "1.0"))
        per_day = float(env.get("ORDERS_PER_DAY", "1000"))
        print(
            f"[태스크 정의] 리비전 {td['revision']} · 이미지 {image_tag_of(td)} · "
            f"REVIEW_RATE={rate:g} (하루 약 {per_day * rate:,.0f}건) · LLM={env.get('LLM', 'bedrock')}"
        )

    running = ecs.list_tasks(cluster=cfg["cluster"], desiredStatus="RUNNING")["taskArns"]
    print(f"[돌고 있는 태스크] {len(running)}개")

    print("[최근 종료 기록]")
    for s in recent_stops(logs, cfg["events_log_group"]) or [{"none": True}]:
        if s.get("none"):
            print("  (최근 7일 없음)")
            break
        ok = (
            "정상"
            if s["stop_code"] == "EssentialContainerExited" and s["exit_code"] == 0
            else "실패"
        )
        print(
            f"  {_ts(s['time'])} {ok} 종료코드={s['exit_code']} {s['stop_code']} {s['reason'][:80]}"
        )

    price = price_of(model)
    print("[최근 실행 (최근 7일, 로그 기준)]")
    runs = recent_runs(logs, cfg["app_log_group"])
    for r in runs[:7]:
        est = (
            f" · 추정 ${r['in'] / 1e6 * price[0] + r['out'] / 1e6 * price[1]:.3f}" if price else ""
        )
        print(
            f"  {_ts(r['time'])} 리뷰 {r['sent']}건 · 버림 {r['skipped']}건 · 토큰 {r['in']:,}/{r['out']:,}{est}"
        )
    if not runs:
        print("  (없음)")

    try:
        part = last_partition(sess.client("s3"), cfg["lake_root"])
        print(f"[S3 리뷰 마지막 날짜] {part or '없음'}")
    except (
        BotoCoreError,
        ClientError,
    ) as e:  # 목록 권한이 없을 수 있다. 상태 화면 전체를 멈추지 않는다
        print(f"[S3 리뷰 마지막 날짜] 확인 못 함 ({type(e).__name__})")

    if args.cost:
        print("[이번 달 청구액 (계정 전체, 서비스별)]")
        for name, amount in month_cost(sess.client("ce", region_name="us-east-1")):
            print(f"  {name}: ${amount:.2f}")
    print(f"대시보드: CloudWatch > 대시보드 > {cfg['dashboard']}")


if __name__ == "__main__":
    main()
