"""RDS 주문으로 실제 리뷰(Bedrock)를 지금 한 번 만든다 (2026-10-21, v0.3.0).

    python deploy/run_rds.py                      # 어제(KST 달력) 리뷰. 비용 안내 후 y 를 눌러야 시작
    python deploy/run_rds.py --date 2026-10-20    # 날짜 지정 (UTC)
    python deploy/run_rds.py --yes                # 확인 없이 바로 시작

하는 일 (순서대로, 하나라도 안 되면 멈춘다)
  1) RDS 접속 주소 secret 에 값이 있는지 본다 (없으면: python deploy/secret.py --orders-db)
  2) 태스크 정의의 주문 입력이 rds 가 아니면 rds 로 바꾼 새 리비전을 등록한다 (switch.py --orders rds 와 같음)
     → 이후 예약 실행(켜 두었다면)도 RDS 주문을 쓴다. 되돌리기: python deploy/switch.py --orders fake
  3) ECS 태스크를 한 번 실행한다. 가짜 문장이 아니라 Bedrock 으로 리뷰를 쓴다(LLM=bedrock 을 이번 실행에 고정)
     → S3 bronze_v2/reviews/year=/month=/day= 그 날짜 파티션을 덮어쓴다

비용: 리뷰 수 ≈ 그날 리뷰 시각인 RDS 주문 항목 수 x REVIEW_RATE. Bedrock 1,000건당 약 $0.21(docs/examples-scorecard.md).
RDS 에 그날 리뷰 시각(배송완료 후 0~7일, 0.3.2)인 주문이 없으면 리뷰 0건으로 정상 종료한다(비용 거의 0).
결과 확인: python deploy/status.py 또는 출력되는 로그 명령 (로그의 "RDS 주문 항목 N건 읽음", "끝: 전송 N건").
"""

from __future__ import annotations

import argparse
import re

from aws_common import (
    env_of,
    follow_new_revision,
    latest_task_definition,
    load_config,
    log_tail_hint,
    register_revision,
    run_task,
    session,
    yesterday_kst,
)
from secret import has_value

# 1,000건당 Bedrock 추정 비용(USD). 확인 문구에만 쓴다. 실제 값은 status.py --cost
COST_PER_1000 = 0.21


def ensure_rds(sess, ecs, cfg: dict) -> dict:
    """접속 secret 을 확인하고, 주문 입력이 rds 인 최신 리비전을 돌려준다(필요하면 새로 등록)."""
    arn = cfg.get("orders_db_secret_arn")
    if not arn:
        raise SystemExit(
            "설정에 orders_db_secret_arn 이 없습니다. infra/stacks/ecs-review-simulator 를 다시 apply 하세요."
        )
    if not has_value(sess.client("secretsmanager"), arn):
        raise SystemExit(
            "RDS 접속 주소 secret 이 비어 있습니다. 먼저 python deploy/secret.py --orders-db"
        )
    td = latest_task_definition(ecs, cfg["task_family"])
    if td is None:
        raise SystemExit(
            "등록된 태스크 정의가 없습니다. 먼저 python deploy/deploy.py 로 배포하세요."
        )
    if env_of(td).get("ORDERS_SOURCE") != "rds":
        td = register_revision(ecs, cfg, env_updates={"ORDERS_SOURCE": "rds"})
        print(f"주문 입력을 rds 로 바꿨습니다 · 리비전 {td['revision']}")
        if follow_new_revision(sess, cfg, td["taskDefinitionArn"]):
            print("스케줄이 켜져 있어 다음 예약 실행부터 RDS 주문을 씁니다")
    return td


def confirm(day: str, rate: str) -> bool:
    print(
        f"\n{day}(UTC) 리뷰를 RDS 주문으로 Bedrock 생성합니다. REVIEW_RATE={rate}\n"
        f"비용: 리뷰 1,000건당 약 ${COST_PER_1000} (리뷰 수 = 그날 리뷰 시각인 주문 항목 x REVIEW_RATE)"
    )
    return input("시작할까요? [y/N] ").strip().lower() in ("y", "yes")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", help="리뷰 날짜(YYYY-MM-DD). 기본 어제(KST 달력)")
    ap.add_argument("--yes", action="store_true", help="비용 확인 없이 바로 시작")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)
    day = args.date or yesterday_kst()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise SystemExit("--date 는 YYYY-MM-DD 로 주세요")

    sess = session(args.region)
    cfg = load_config(sess)
    ecs = sess.client("ecs")
    td = ensure_rds(sess, ecs, cfg)
    if not args.yes and not confirm(day, env_of(td).get("REVIEW_RATE", "?")):
        print("취소했습니다 (주문 입력 rds 설정은 그대로 남습니다)")
        return
    # LLM=bedrock 을 이번 실행에 고정한다(태스크 정의에 fake 가 들어 있어도 실제 생성)
    arn = run_task(ecs, cfg, env={"RUN_DATE": day, "LLM": "bedrock"}, started_by="run-rds")
    print(
        f"태스크 시작: {arn.rsplit('/', 1)[-1]} (리뷰 날짜 {day} UTC, 주문 = RDS, 문장 = Bedrock)"
    )
    print("로그 보기:", log_tail_hint(cfg, arn))
    print("끝난 뒤: python deploy/status.py")


if __name__ == "__main__":
    main()
