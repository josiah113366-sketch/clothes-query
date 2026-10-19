"""실행 모드(리뷰 작성 비율 REVIEW_RATE)를 바꾼다 (2026-10-18 sim/review-ecs).

    python deploy/switch.py --show        # 지금 값
    python deploy/switch.py low           # 0.1  → 하루 약 100건
    python deploy/switch.py normal        # 0.5  → 하루 약 500건
    python deploy/switch.py high          # 1.0  → 하루 약 1,000건 (2026-10-14 목표량)
    python deploy/switch.py --rate 0.3    # 직접 지정 (0 초과 1 이하)

하루 리뷰 수 ≈ ORDERS_PER_DAY(가짜 주문 하루 1,000건) x REVIEW_RATE. 로컬 .env 의 REVIEW_RATE 와 같은 값이다.
REVIEW_RATE 만 바꾼 새 태스크 정의 리비전을 등록하고, 스케줄이 켜져 있으면 스케줄도 새 리비전으로 바꾼다.
비용은 리뷰 수에 거의 비례한다(1,000건당 Bedrock 약 $0.21, docs/examples-scorecard.md).
"""

from __future__ import annotations

import argparse

from aws_common import (
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("preset", nargs="?", choices=list(RATE_PRESETS))
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
    print(
        f"지금: REVIEW_RATE={cur:g} ({preset_name(cur)}, 하루 약 {per_day * cur:,.0f}건) · 리비전 {td['revision']}"
    )
    if args.show:
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
