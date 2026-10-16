"""직접 작성한 리뷰를 레이크에 넣는다 (rsim inject, 2026-10-16 lemin 결정).

언제 쓰나
---------
특정 문장·상황을 일부러 넣어서 파이프라인(감성분석 → 이상탐지)을 시험할 때 쓴다.
예) "사이즈 불만 리뷰 30건을 10월 8일에 몰아 넣으면 이상탐지가 잡는가", "이 문장을 모델이 어떻게 읽는가".
LLM 을 부르지 않으므로 비용이 들지 않는다.

입력 파일 (CSV 또는 JSONL, 확장자로 구분. 예시: data/manual_reviews.example.csv)
-------------------------------------------------------------------------------
필수 : text, rating(1~5), product_id
선택 : created_at, order_id, member_id, product_name, category, option_size, option_color,
       has_photo, age_group, purchased_at, aspects
- created_at
    없으면 지금 시각(UTC). 시간대가 없으면 한국 시각(+09:00)으로 본다(사람이 직접 쓰는 값이라서).
    날짜만 쓰면(2026-10-08) 그날 한국 시각 정오로 본다. 자정으로 두면 UTC 로 바꿀 때 전날 파티션에 들어가기 때문이다.
- product_id 가 상품 목록(catalog.py)에 있으면 product_name·category 를 거기서 채운다.
  목록에 없는 상품이면 product_name 을 직접 적어야 한다. category 는 선택(적으면 taxonomy.CATEGORIES 중 하나).
- aspects (정답 라벨, 선택)
    CSV  : "사이즈·핏:부정|배송:긍정"  (속성:감성 을 | 로 이어 쓴다. 속성 11개·감성 3개는 taxonomy.py)
    JSONL: 위 문자열 또는 [{"aspect": "사이즈·핏", "sentiment": "부정"}, ...]
    적으면 정답(reviews_truth)에도 한 줄을 쓴다. 비워 두면 리뷰만 쓴다.
- 빈 칸(review_id, member_id, 옵션, has_photo 등)은 시뮬레이터가 채운다.

어디에 쓰나
-----------
LAKE_ROOT 의 같은 날짜 파티션에 **파일 이름만 다르게** 쓴다.
    <LAKE_ROOT>/reviews/year=2026/month=10/day=08/part-manual-<입력 파일 이름>.jsonl
- 매일 도는 rsim run --sink lake 는 part-00000.jsonl 만 덮어쓰므로 직접 넣은 리뷰가 지워지지 않는다.
  Athena·Glue 는 폴더 안 파일을 모두 읽으니 조회할 때는 하나의 테이블로 보인다.
- 같은 입력 파일을 다시 넣으면 같은 파일을 덮어쓴다(중복으로 쌓이지 않음).
  review_id 도 (입력 파일 이름, 줄 번호)로 정하므로 다시 넣어도 같은 ID 다.
  다른 묶음으로 넣으려면 입력 파일 이름을 바꾼다.
- 구별 표시: review_id 가 "M-" 로 시작하고, source 칸이 "manual" 이다(시뮬레이터 생성분은 "simulator").
  나중에 테스트 데이터만 지우려면 part-manual-* 파일을 지우면 된다.

ECS 에서
--------
컨테이너는 PC 파일을 못 읽으므로 입력 파일을 S3 에 올리고 경로를 s3:// 로 준다.
    rsim inject --file s3://<버킷>/sim-input/manual/size_spike_1008.csv
매일 도는 작업과 같은 태스크 정의로 ECS RunTask 를 한 번 실행하고 명령(command)만 위처럼 바꿔 준다.

개인정보 주의
------------
여기에 넣는 문장은 **직접 지어낸 테스트 문장**이어야 한다. 실제 쇼핑몰 리뷰를 옮겨 적은 것(review-analysis/private)은
S3 에 올리면 안 되므로, 경로에 "private" 가 들어가면 읽지 않고 멈춘다.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import random
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath

from rsim import SCHEMA_VERSION, TRUTH_SCHEMA_VERSION

from ..common.rng import derive_seed, make_rng, seeded_uuid
from .catalog import Catalog
from .options import pick_options
from .orders import ORDER_HASH_SALT, catalog_rng
from .taxonomy import ASPECTS, CATEGORIES, SENTIMENTS

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
# 리뷰 이벤트의 source 칸 값. 시뮬레이터가 만든 리뷰("simulator")와 구별한다
SOURCE = "manual"
# 생성 정보 칸(truth.generator.model_id)에 넣는 값. LLM 으로 만든 문장이 아니라는 표시
MODEL_ID = "manual"

REQUIRED = ("text", "rating", "product_id")
# 이 칸들은 입력 파일에 값이 있으면 그대로 쓰고, 비어 있으면 시뮬레이터가 채운다
OPTIONAL = (
    "created_at",
    "order_id",
    "member_id",
    "product_name",
    "category",
    "option_size",
    "option_color",
    "has_photo",
    "age_group",
    "purchased_at",
    "aspects",
)


# ---------------------------------------------------------------- 입력 읽기
def _read_text(path: str, region: str | None = None) -> str:
    """로컬 파일 또는 s3://버킷/키 를 문자열로 읽는다. S3 는 boto3 기본 자격 증명(ECS 태스크 역할 등)."""
    if path.startswith("s3://"):
        from .sinks import s3_client

        bucket, _, key = path[len("s3://") :].partition("/")
        body = s3_client(region).get_object(Bucket=bucket, Key=key)["Body"].read()
        return body.decode("utf-8-sig")
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"입력 파일이 없습니다: {path}")
    return p.read_text(encoding="utf-8-sig")  # 엑셀에서 저장한 CSV 의 BOM 을 떼어 낸다


def read_rows(path: str, region: str | None = None) -> list[dict]:
    """CSV(.csv) 또는 JSONL(.jsonl/.json) 을 dict 목록으로 읽는다. 빈 줄은 건너뛴다."""
    if "private" in path.replace("\\", "/").lower().split("/"):
        raise SystemExit("private 폴더의 파일은 넣을 수 없습니다 (실제 리뷰 원문 보호)")
    text = _read_text(path, region)
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    if suffix == ".csv":
        rows = csv.DictReader(io.StringIO(text))
        return [r for r in rows if any((v or "").strip() for v in r.values())]
    if suffix in (".jsonl", ".json"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    raise SystemExit(f"CSV 또는 JSONL 파일만 넣을 수 있습니다: {path}")


# ---------------------------------------------------------------- 칸별 해석
def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def parse_created_at(v, now: datetime) -> datetime:
    """created_at 해석. 위 모듈 설명의 규칙(없으면 지금, 시간대 없으면 KST, 날짜만이면 KST 정오)."""
    if _blank(v):
        return now
    s = str(v).strip()
    t = datetime.fromisoformat(s)
    if len(s) == 10:  # 날짜만 (YYYY-MM-DD)
        t = datetime.combine(t.date(), time(12, 0), tzinfo=KST)
    elif t.tzinfo is None:
        t = t.replace(tzinfo=KST)
    return t.replace(microsecond=0)


def parse_aspects(v) -> list[dict] | None:
    """정답 라벨 해석. 빈 값이면 None(라벨 없음). 속성·감성 이름이 틀리면 ValueError."""
    if _blank(v):
        return None
    if isinstance(v, str):
        items = []
        for part in v.split("|"):
            aspect, sep, sentiment = part.strip().partition(":")
            if not sep:
                raise ValueError(f"aspects 형식은 '속성:감성|속성:감성' 입니다: {part!r}")
            items.append({"aspect": aspect.strip(), "sentiment": sentiment.strip()})
    else:
        items = [{"aspect": a["aspect"], "sentiment": a["sentiment"]} for a in v]
    for a in items:
        if a["aspect"] not in ASPECTS:
            raise ValueError(f"모르는 속성 {a['aspect']!r} (가능: {', '.join(ASPECTS)})")
        if a["sentiment"] not in SENTIMENTS:
            raise ValueError(f"모르는 감성 {a['sentiment']!r} (가능: {', '.join(SENTIMENTS)})")
    return items


def _parse_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "y", "yes", "o", "있음"):
        return True
    if s in ("false", "0", "n", "no", "x", "없음"):
        return False
    raise ValueError(f"has_photo 는 true/false 로 적어 주세요: {v!r}")


# ---------------------------------------------------------------- 한 줄 → 이벤트
def build_manual_events(
    row: dict, batch: str, index: int, catalog: Catalog, now: datetime
) -> tuple[dict, dict | None]:
    """입력 한 줄 → (리뷰 이벤트, 정답 이벤트 또는 None). 모양은 run.build_events 와 같다(review.v2).

    batch : 입력 파일 이름(확장자 뺀 것). ID 와 출력 파일 이름에 쓴다
    index : 입력 파일 안의 줄 번호(1부터). 같은 파일·같은 줄이면 항상 같은 review_id 가 나온다
    잘못된 값이 있으면 ValueError (호출하는 쪽이 줄 번호를 붙여 모아서 보여 준다)
    """
    missing = [k for k in REQUIRED if _blank(row.get(k))]
    if missing:
        raise ValueError(f"필수 칸이 비었습니다: {', '.join(missing)}")
    unknown = sorted(set(row) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise ValueError(f"모르는 칸: {', '.join(unknown)} (오타인지 확인)")

    rating = int(str(row["rating"]).strip())
    if not 1 <= rating <= 5:
        raise ValueError(f"rating 은 1~5 입니다: {rating}")

    product_id = str(row["product_id"]).strip()
    product = catalog.by_id.get(product_id)
    product_name = row.get("product_name") if not _blank(row.get("product_name")) else None
    category = row.get("category") if not _blank(row.get("category")) else None
    if product:
        product_name = product_name or product.product_name
        category = category or product.category
    if not product_name:
        raise ValueError(
            f"상품 목록에 없는 product_id({product_id}) 는 product_name 을 적어야 합니다"
        )
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"모르는 category {category!r} (가능: {', '.join(CATEGORIES)})")

    created_at = parse_created_at(row.get("created_at"), now)
    aspects = parse_aspects(row.get("aspects"))

    # 이 줄 전용 난수: (입력 파일 이름, 줄 번호)로만 정한다 → 다시 넣어도 같은 ID·같은 옵션
    rng: random.Random = make_rng(derive_seed(ORDER_HASH_SALT, "manual", batch, index))
    review_id = f"M-{seeded_uuid(rng).hex[:12]}"
    event_id = str(seeded_uuid(rng))
    member_id = row.get("member_id") or f"C-{seeded_uuid(rng).hex[:10]}"
    # 비어 있는 옵션만 아래에서 이 값으로 채운다. 상품 목록에 색상이 있으면 그 색이 기본값
    info = product.info if product else {}
    opts = pick_options(category, rng, info.get("color"), info.get("product_type"))
    if not _blank(row.get("option_size")):
        opts["option_size"] = str(row["option_size"]).strip()
    if not _blank(row.get("option_color")):
        opts["option_color"] = str(row["option_color"]).strip()
    if not _blank(row.get("has_photo")):
        opts["has_photo"] = _parse_bool(row["has_photo"])

    purchased_at = None
    if not _blank(row.get("purchased_at")):
        purchased_at = parse_created_at(row["purchased_at"], now).isoformat()

    text = str(row["text"]).strip()
    review = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": "review_created",
        "review_id": review_id,
        "created_at": created_at.isoformat(),
        "order_id": row.get("order_id") or None,
        "product_id": product_id,
        "product_name": product_name,
        "category": category,
        **opts,
        "member_id": member_id,
        "purchased_at": purchased_at,
        "age_group": row.get("age_group") or None,
        "rating": rating,
        "text": text,
        "source": SOURCE,
        "emitted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    if aspects is None:
        return review, None
    truth = {
        "schema_version": TRUTH_SCHEMA_VERSION,
        "review_id": review_id,
        "order_id": review["order_id"],
        "created_at": review["created_at"],
        "product_id": product_id,
        "category": category,
        "rating": rating,
        "text": text,
        "aspects": aspects,
        "spec_aspects": aspects,
        "incident_id": None,
        "generator": {"model_id": MODEL_ID, "prompt_version": None, "style": None, "length": None},
    }
    return review, truth


# ---------------------------------------------------------------- rsim inject 본체
def batch_name(path: str) -> str:
    """입력 경로 → 묶음 이름(파일 이름에서 확장자를 뺀 것). 출력 파일 part-manual-<묶음>.jsonl 에 쓴다."""
    name = PurePosixPath(path.replace("\\", "/")).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe or "manual"


def run_inject(*, file: str, sink_kind: str = "lake", dry_run: bool = False) -> int:
    """입력 파일을 검사하고 레이크(또는 콘솔)에 쓴다. 반환: 넣은 리뷰 수.

    한 줄이라도 잘못되면 아무것도 쓰지 않고 줄 번호별 오류를 모두 보여 준다(일부만 들어가는 일 방지).
    dry_run 이면 검사만 하고 쓰지 않는다.
    """
    from ..common.config import load_settings
    from .seeds import SeedPool
    from .sinks import LakeSink, StdoutSink

    settings = load_settings()
    rows = read_rows(file, settings.aws_region)
    if not rows:
        raise SystemExit(f"입력 파일에 리뷰가 없습니다: {file}")
    # 상품 목록은 주문 모드와 같은 고정 난수로 만든다(같은 product_id → 같은 상품명)
    seeds = SeedPool.load(settings.seeds_path, make_rng(0))
    catalog = Catalog.build(settings.products_path, seeds.product_names(), catalog_rng())

    batch = batch_name(file)
    now = datetime.now(UTC).replace(microsecond=0)
    events, errors = [], []
    for i, row in enumerate(rows, start=1):
        try:
            events.append(build_manual_events(row, batch, i, catalog, now))
        except (ValueError, KeyError, TypeError) as e:
            errors.append(f"  {i}번째 리뷰: {e}")
    if errors:
        raise SystemExit(
            "입력 파일에 고칠 곳이 있어 아무것도 쓰지 않았습니다.\n" + "\n".join(errors)
        )

    labeled = sum(t is not None for _, t in events)
    log.info("검사 통과: 리뷰 %d건 (정답 라벨 있음 %d건), 묶음=%s", len(events), labeled, batch)
    if dry_run:
        return 0

    if sink_kind == "stdout":
        sink = StdoutSink()
    else:
        sink = LakeSink(
            settings.lake_root,
            settings.lake_truth_root,
            settings.aws_region,
            file_name=f"part-manual-{batch}.jsonl",
        )
    for review, truth in events:
        sink.send(review, truth)
    sink.close()
    return len(events)
