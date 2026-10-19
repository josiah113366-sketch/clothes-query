"""특정 상품(또는 카테고리)의 긍정·부정 리뷰 비율을 올려 하루치를 한 번 실행한다 (2026-10-18 sim/review-ecs).

    python deploy/run_incident.py --product-id W-0003 --aspect 품질·내구성 --sentiment 부정 --share 0.6 --date 2026-10-17
    python deploy/run_incident.py --category 패션슈즈 --aspect 배송 --sentiment 부정 --share 0.4
    python deploy/run_incident.py --product-id W-0003 --aspect 색상·디자인 --sentiment 긍정 --share 0.8 --dry-run

이미 있는 이상 상황(incidents) 기능을 그대로 쓴다(scenario.Incident, data/incidents.example.json).
그날 그 상품 리뷰 중 share 비율에 지정한 속성·감성이 들어간다. 부정이면 별점도 1~3점으로 내려간다.
로컬에서 INCIDENTS_PATH 에 같은 JSON 을 두고 rsim run --source orders --date D 를 돌린 것과 같은 결과다.

하는 일
  1. 입력 확인 (속성·감성 이름, 상품 ID 가 상품 목록에 있는지: .local/seeds.jsonl 이 있으면 확인)
  2. incidents JSON 을 S3 sim-input/review-simulator/incidents/<id>.json 에 올림
  3. 그 날짜로 태스크를 한 번 실행 (INCIDENTS_PATH, RUN_DATE 만 이번 실행에 덮어씀)
그날 파티션(part-00000.jsonl)을 이 실행 결과로 덮어쓴다. 원래대로 돌리려면 같은 날짜로 onoff.py once.
volume_multiplier(리뷰 수 늘리기)는 무작위 모드 전용이라 주문 기반 실행에는 효과가 없어 받지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta

from aws_common import load_config, log_tail_hint, run_task, session, upload_input, yesterday_utc


def build_incident(
    *,
    day: str,
    aspect: str,
    sentiment: str,
    share: float,
    product_id: str | None = None,
    category: str | None = None,
    incident_id: str | None = None,
    note: str = "",
) -> dict:
    """incidents.json 한 항목. 그날 0시~다음날 0시(UTC)에만 적용된다(리뷰 날짜 = UTC)."""
    from rsim.review.taxonomy import ASPECTS, CATEGORIES, SENTIMENTS

    if aspect not in ASPECTS:
        raise SystemExit(f"속성 이름이 틀렸습니다: {aspect} (가능: {', '.join(ASPECTS)})")
    if sentiment not in SENTIMENTS:
        raise SystemExit(f"감성은 {', '.join(SENTIMENTS)} 중 하나입니다")
    if (product_id is None) == (category is None):
        raise SystemExit("--product-id 또는 --category 중 하나만 주세요")
    if category is not None and category not in CATEGORIES:
        raise SystemExit(f"카테고리 이름이 틀렸습니다: {category} (가능: {', '.join(CATEGORIES)})")
    if not 0 < share <= 1:
        raise SystemExit("--share 는 0 초과 1 이하입니다")
    d = date.fromisoformat(day)
    target = product_id or category
    item = {
        "id": incident_id or f"INC-{d:%Y%m%d}-{re.sub(r'[^A-Za-z0-9-]', '', target) or 'cat'}",
        "aspect": aspect,
        "sentiment": sentiment,
        "start": f"{d.isoformat()}T00:00:00+00:00",
        "end": f"{(d + timedelta(days=1)).isoformat()}T00:00:00+00:00",
        "share": share,
        "note": note or "deploy/run_incident.py",
    }
    if product_id:
        item["product_id"] = product_id
    else:
        item["category"] = category
    return item


def check_product(product_id: str) -> str | None:
    """상품 ID 가 시뮬레이터 상품 목록에 있는지 본다. 이미지와 같은 .local/seeds.jsonl 이 있을 때만 확인할 수 있다.

    반환: 상품명 (확인 못 하면 None). 목록에 없으면 멈춘다(그 상품 주문이 없어 아무 효과가 없으니까).
    """
    from rsim.common.config import load_settings
    from rsim.common.rng import make_rng
    from rsim.review.catalog import Catalog
    from rsim.review.orders import catalog_rng
    from rsim.review.seeds import SeedPool

    settings = load_settings()
    if not settings.seeds_path.exists():
        print(f"참고: {settings.seeds_path} 이 없어 상품 ID 를 확인하지 않았습니다")
        return None
    seeds = SeedPool.load(settings.seeds_path, make_rng(0))
    catalog = Catalog.build(settings.products_path, seeds.product_names(), catalog_rng())
    for p in catalog.products:
        if p.product_id == product_id:
            return p.product_name
    sample = ", ".join(p.product_id for p in catalog.products[:5])
    raise SystemExit(f"상품 목록에 {product_id} 가 없습니다 (예: {sample} …)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--product-id")
    target.add_argument("--category")
    ap.add_argument(
        "--aspect", required=True, help="속성 (taxonomy.py 11개 중 하나, 예: 사이즈·핏)"
    )
    ap.add_argument("--sentiment", required=True, choices=["긍정", "중립", "부정"])
    ap.add_argument(
        "--share", type=float, default=0.6, help="그 상품 리뷰 중 이 속성·감성이 들어갈 비율"
    )
    ap.add_argument("--date", help="리뷰 날짜(UTC, YYYY-MM-DD). 기본 어제")
    ap.add_argument("--id", dest="incident_id", help="이상 상황 ID (기본 INC-<날짜>-<상품>)")
    ap.add_argument("--note", default="")
    ap.add_argument("--fake", action="store_true", help="가짜 문장(Bedrock 비용 0원, 배관 확인용)")
    ap.add_argument(
        "--dry-run", action="store_true", help="JSON 만 보여 주고 올리거나 실행하지 않음"
    )
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    day = args.date or yesterday_utc()
    item = build_incident(
        day=day,
        aspect=args.aspect,
        sentiment=args.sentiment,
        share=args.share,
        product_id=args.product_id,
        category=args.category,
        incident_id=args.incident_id,
        note=args.note,
    )
    if args.product_id:
        name = check_product(args.product_id)
        if name:
            print(f"상품: {args.product_id} {name}")
    body = json.dumps([item], ensure_ascii=False, indent=2)
    print(body)
    if args.dry_run:
        print("--dry-run: 올리거나 실행하지 않았습니다")
        return

    sess = session(args.region)
    cfg = load_config(sess)
    uri = upload_input(sess, cfg, "incidents", f"{item['id']}.json", body.encode("utf-8"))
    env = {"INCIDENTS_PATH": uri, "RUN_DATE": day}
    if args.fake:
        env["LLM"] = "fake"
    arn = run_task(sess.client("ecs"), cfg, env=env, started_by=f"incident-{item['id']}")
    print(f"올림: {uri}")
    print(f"태스크 시작: {arn.rsplit('/', 1)[-1]} (리뷰 날짜 {day})")
    print("로그 보기:", log_tail_hint(cfg, arn))


if __name__ == "__main__":
    main()
