"""실행 모드(리뷰 작성 비율 REVIEW_RATE)를 바꾼다 (2026-10-18 sim/review-ecs).

    python deploy/switch.py --show        # 지금 값
    python deploy/switch.py low           # 0.1  → 하루 약 100건
    python deploy/switch.py normal        # 0.5  → 하루 약 500건
    python deploy/switch.py high          # 1.0  → 하루 약 1,000건 (2026-10-14 목표량)
    python deploy/switch.py --rate 0.3    # 직접 지정 (0 초과 1 이하)
    python deploy/switch.py --orders rds  # 주문 입력을 RDS orders 테이블로 (2026-10-21)
    python deploy/switch.py --orders fake # 가짜 주문으로 되돌리기

주문 입력(ORDERS_SOURCE)을 rds 로 바꾸기 전에 할 일 (deploy/README.md "RDS 주문 읽기")
  1) RDS 담당: infra/stacks/rds 의 database_clients 에 이 태스크 보안 그룹을 넣고 apply
  2) DB 에 읽기 전용 계정 만들기
  3) python deploy/secret.py --orders-db  (접속 주소 저장. 비어 있으면 이 스크립트가 rds 전환을 막는다)

하루 리뷰 수 ≈ ORDERS_PER_DAY(가짜 주문 하루 1,000건) x REVIEW_RATE. 로컬 .env 의 REVIEW_RATE 와 같은 값이다.
REVIEW_RATE 만 바꾼 새 태스크 정의 리비전을 등록하고, 스케줄이 켜져 있으면 스케줄도 새 리비전으로 바꾼다.
비용은 리뷰 수에 거의 비례한다(1,000건당 Bedrock 약 $0.21, docs/examples-scorecard.md).
"""

from __future__ import annotations

import argparse

from aws_common import (
    ORDERS_SOURCES,
    RATE_PRESETS,
    env_of,
    follow_new_revision,
    latest_task_definition,
    load_config,
    register_revision,
    session,
)


def preset_name(rate: float) -> str:
    for name, value in RATE_PRESETS.items():
        if abs(value - rate) < 1e-9:
            return name
    return "직접 지정"


def parse_rate(preset: str | None, rate: float | None) -> float:
    if (preset is None) == (rate is None):
        raise SystemExit("low / normal / high 중 하나 또는 --rate 하나만 주세요 (지금 값은 --show)")
    value = RATE_PRESETS[preset] if preset else rate
    if not 0 < value <= 1:
        raise SystemExit("--rate 는 0 초과 1 이하로 주세요")
    return value


def switch_orders(sess, ecs, cfg: dict, cur: str, new: str) -> None:
    """주문 입력(ORDERS_SOURCE)만 바꾼 새 리비전을 등록한다. rds 로 바꿀 때는 접속 secret 값이 있는지 먼저 본다."""
    if new == cur:
        print("같은 값이라 바꾸지 않았습니다")
        return
    if new == "rds":
        from secret import has_value  # 같은 deploy/ 폴더 (값은 읽지 않고 들어 있는지만 본다)

        arn = cfg.get("orders_db_secret_arn")
        if not arn:
            raise SystemExit(
                "설정에 orders_db_secret_arn 이 없습니다. infra/stacks/ecs-review-simulator 를 다시 apply 하세요."
            )
        if not has_value(sess.client("secretsmanager"), arn):
            raise SystemExit(
                "RDS 접속 주소 secret 이 비어 있습니다. 먼저 python deploy/secret.py --orders-db"
            )
    td = register_revision(ecs, cfg, env_updates={"ORDERS_SOURCE": new})
    print(f"변경: 주문 {cur} → {new} · 리비전 {td['revision']}")
    if new == "rds":
        print("한 번 확인: python deploy/onoff.py once --fake  (가짜 문장, Bedrock 비용 0원)")
    if follow_new_revision(sess, cfg, td["taskDefinitionArn"]):
        print("스케줄이 켜져 있어 다음 예약 실행부터 적용됩니다")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("preset", nargs="?", choices=list(RATE_PRESETS))
    ap.add_argument(
        "--orders",
        choices=list(ORDERS_SOURCES),
        help="주문 입력: fake(가짜 주문) / rds(RDS orders)",
    )
    ap.add_argument("--rate", type=float)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    cfg = load_config(sess)
    ecs = sess.client("ecs")
    td = latest_task_definition(ecs, cfg["task_family"])
    if td is None:
        raise SystemExit(
            "등록된 태스크 정의가 없습니다. 먼저 python deploy/deploy.py 로 배포하세요."
        )
    env = env_of(td)
    cur = float(env.get("REVIEW_RATE", "1.0"))
    per_day = float(env.get("ORDERS_PER_DAY", "1000"))
    cur_orders = env.get("ORDERS_SOURCE", "fake")
    print(
        f"지금: REVIEW_RATE={cur:g} ({preset_name(cur)}, 하루 약 {per_day * cur:,.0f}건) · "
        f"주문 {cur_orders} · 리비전 {td['revision']}"
    )
    if args.show:
        return

    if args.orders:
        # 주문 입력만 바꾼다 (비율과 한 번에 바꾸지 않는다: 한 번에 하나씩 바꿔야 결과 차이를 알아보기 쉽다)
        if args.preset or args.rate is not None:
            raise SystemExit("--orders 는 비율(low/normal/high/--rate)과 따로 바꿔 주세요")
        switch_orders(sess, ecs, cfg, cur_orders, args.orders)
        return

    value = parse_rate(args.preset, args.rate)
    if abs(value - cur) < 1e-9:
        print("같은 값이라 바꾸지 않았습니다")
        return
    new = register_revision(ecs, cfg, env_updates={"REVIEW_RATE": f"{value:g}"})
    print(
        f"변경: REVIEW_RATE={value:g} ({preset_name(value)}, 하루 약 {per_day * value:,.0f}건) · 리비전 {new['revision']}"
    )
    if follow_new_revision(sess, cfg, new["taskDefinitionArn"]):
        print("스케줄이 켜져 있어 다음 예약 실행부터 적용됩니다")


if __name__ == "__main__":
    main()
