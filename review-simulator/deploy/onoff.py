"""하루 1번 예약 실행을 켜고 끄거나, 지금 한 번 실행한다 (2026-10-18 sim/review-ecs).

    python deploy/onoff.py on                    # 예약 실행 켜기 (최신 리비전으로 맞춤)
    python deploy/onoff.py off                   # 예약 실행 끄기 + 돌고 있는 태스크 멈춤
    python deploy/onoff.py once                  # 지금 한 번: 어제(KST 달력) 리뷰
    python deploy/onoff.py once --date 2026-10-17 --fake   # 날짜 지정, 가짜 문장(Bedrock 비용 0원)

예약 실행 = 매일 00:00 KST 에 어제(KST 달력) 리뷰를 만들어 S3 bronze 날짜 파티션에 덮어쓴다.
(2026-10-23 lemin: 00:30 UTC → 00:00 KST. 주문 시뮬레이터가 KST 시각을 UTC 처럼 넣어서 날짜 D = KST 날짜 D)
2026-10-18 lemin: 계속 실행은 보류라 Terraform 은 꺼진 상태로 만든다. 켜는 것은 이 스크립트로만 한다.
같은 날짜를 다시 실행하면 그날 파티션(part-00000.jsonl)을 덮어쓴다. 직접 넣은 리뷰(part-manual-*)는 그대로 남는다.
"""

from __future__ import annotations

import argparse

from aws_common import (
    latest_task_definition,
    load_config,
    log_tail_hint,
    run_task,
    session,
    update_schedule,
)


def stop_running(ecs, cfg: dict, reason: str = "onoff.py off") -> list[str]:
    """클러스터에서 돌고 있는 태스크를 멈춘다. 멈추면 SIGTERM → 현재 배치까지만 쓰고 끝난다(run.py)."""
    arns = ecs.list_tasks(cluster=cfg["cluster"], desiredStatus="RUNNING")["taskArns"]
    for arn in arns:
        ecs.stop_task(cluster=cfg["cluster"], task=arn, reason=reason)
    return arns


def turn_on(sess, cfg: dict) -> str:
    td = latest_task_definition(sess.client("ecs"), cfg["task_family"])
    if td is None:
        raise SystemExit(
            "등록된 태스크 정의가 없습니다. 먼저 python deploy/deploy.py 로 배포하세요."
        )
    update_schedule(
        sess.client("scheduler"), cfg, state="ENABLED", task_def_arn=td["taskDefinitionArn"]
    )
    return td["taskDefinitionArn"]


def turn_off(sess, cfg: dict) -> list[str]:
    update_schedule(sess.client("scheduler"), cfg, state="DISABLED")
    return stop_running(sess.client("ecs"), cfg)


def run_once(sess, cfg: dict, day: str | None, fake: bool) -> str:
    env = {}
    if day:
        env["RUN_DATE"] = day
    if fake:
        env["LLM"] = "fake"
    return run_task(sess.client("ecs"), cfg, env=env, started_by="onoff-once")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("action", choices=["on", "off", "once"])
    ap.add_argument("--date", help="once: 리뷰 날짜(YYYY-MM-DD). 기본 어제(KST 달력)")
    ap.add_argument("--fake", action="store_true", help="once: 가짜 문장(Bedrock 호출 없음)")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    cfg = load_config(sess)
    if args.action == "on":
        arn = turn_on(sess, cfg)
        print(f"예약 실행 켬: {cfg['schedule_name']} → {arn.rsplit('/', 1)[-1]}")
    elif args.action == "off":
        stopped = turn_off(sess, cfg)
        print(f"예약 실행 끔: {cfg['schedule_name']} (멈춘 태스크 {len(stopped)}개)")
    else:
        arn = run_once(sess, cfg, args.date, args.fake)
        print(f"태스크 시작: {arn.rsplit('/', 1)[-1]}")
        print("로그 보기:", log_tail_hint(cfg, arn))


if __name__ == "__main__":
    main()
