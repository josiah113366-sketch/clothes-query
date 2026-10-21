"""리뷰 생성 실행 흐름: 명세 → 생성(+검수) → 이벤트 → 전송.  (명령은 rsim run, cli.py 참고)

자주 쓰는 실행 예 (review-simulator/ 폴더에서)
-----------------------------------------------
# 1) Bedrock 없이 가짜 문장으로 콘솔 출력 (설치 확인용, 비용 0원)
rsim run --llm fake --sink stdout --count 5

# 2) 가짜 문장으로 로컬 Kafka 전송 (Kafka 배관 확인)
rsim run --llm fake --sink kafka --count 50

# 3) Bedrock 으로 진짜 리뷰 20건 만들어 Kafka 로 전송
rsim run --sink kafka --count 20

# 4) 과거 3일치 데이터를 시간당 30건 속도로 만들어 파일로 저장 (이상탐지 시험용, data/incidents.json 적용)
rsim run --sink jsonl --start 2026-10-10T00:00:00+09:00 --reviews-per-hour 30 --count 2160

# 5) 멈출 때까지 계속 생성 (ECS 에서 상시 실행할 때) — 초당 최대 0.5건
rsim run --sink kafka --count 0 --max-rps 0.5

주문 기반 실행 (--source orders, 2026-10-14 결정, 2026-10-21 에 기간만 1~7일로 좁힘: 결제 후 1~7일 뒤 리뷰 → S3 에 날짜별로 저장)
-------------------------------------------------------------------------------------------
# 6) 가짜 주문 14일치(하루 1000건)를 만들고, 10월 8일(UTC) 하루에 리뷰 시각이 떨어지는 주문에 리뷰를 단다
#    → .local/lake/reviews/year=2026/month=10/day=08/part-00000.jsonl (정답은 reviews_truth/)
rsim orders-fake --start 2026-10-01T00:00:00+09:00 --days 14 --per-day 1000
rsim run --source orders --llm fake --sink lake --date 2026-10-08

# 7) 같은 날짜를 다시 돌리면 그 날짜 파티션을 덮어쓴다(주문당 리뷰 하나). 다음 날은 --date 2026-10-09

RDS orders 테이블 기반 실행 (--source rds, 2026-10-21 lemin 결정)
------------------------------------------------------------------
# 8) 업무 API 가 RDS 에 저장한 주문을 읽어(.env 의 ORDERS_DATABASE_URL) 10월 21일(UTC) 리뷰를 단다.
#    주문 항목(상품) 하나에 리뷰 하나. 상품 정보·회원 연령대도 RDS 에서 읽어 프롬프트에 넣는다.
rsim run --source rds --llm fake --sink lake --date 2026-10-21
"""

from __future__ import annotations

import logging
import random
import signal
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from rsim import SCHEMA_VERSION, TRUTH_SCHEMA_VERSION
from rsim.common.config import load_settings
from rsim.common.rng import derive_seed, make_rng, resolve_seed, seeded_uuid

from .catalog import Catalog
from .generator import PROMPT_VERSION, FakeGenerator, make_generator
from .options import pick_options
from .orders import (
    JsonlOrderSource,
    Order,
    OrderSource,
    RdsOrderSource,
    ReviewTiming,
    catalog_rng,
    due_orders,
    order_id_rng,
)
from .scenario import ReviewSpec, ScenarioEngine, SimClock, load_incidents
from .seeds import SeedPool
from .sinks import JsonlSink, KafkaSink, LakeSink, StdoutSink

log = logging.getLogger("rsim")


def build_events(
    spec: ReviewSpec,
    generated: dict,
    model_id: str,
    rng: random.Random,
    order: Order | None = None,
    attr_rng: random.Random | None = None,
    examples_version: str | None = None,
) -> tuple[dict, dict]:
    """명세 + 생성된 문장 → (리뷰 이벤트, 정답 이벤트) 두 개를 만든다.

    두 이벤트는 서로 다른 토픽으로 간다 (2026-10-13 결정).

    1) 리뷰 이벤트  → KAFKA_TOPIC (기본 reviews.raw)
       실제 쇼핑몰에서 들어올 리뷰와 **같은 모양**만 담는다. 정답 라벨이 없으므로
       운영 파이프라인(감성분석 → 이상탐지)은 실제 운영과 똑같은 조건으로 이 토픽만 읽는다.
       (제목 칸은 국내 쇼핑몰에 보통 없어서 두지 않음)

    2) 정답 이벤트  → KAFKA_TRUTH_TOPIC (기본 reviews.truth)
       시뮬레이터만 아는 정답(의도한 속성·감성, 이상 상황 ID)과 생성 조건.
       리뷰 본문(text)도 같이 넣어서 이 토픽만으로 학습 데이터(본문 + 라벨)가 완성되게 한다.
       → 학습·평가 쪽은 운영 흐름과 별개 방향으로 이 토픽을 소비한다.
       두 토픽은 review_id 로 이어 붙일 수 있다.

    review_id·event_id 는 시드 고정 난수(rng)로 만든다. 같은 시드로 다시 돌리면 같은 ID 가 나오므로,
    이미 보낸 토픽에 다시 보낼 때는 RANDOM_SEED 를 바꾸거나 비워 둔다.
    (주문 모드는 run() 이 order_id 로 만든 난수를 넘겨서, 같은 주문이면 항상 같은 ID 가 나온다)

    order    : 주문 모드의 주문. 무작위 모드는 None → order_id·purchased_at 이 null
    attr_rng : 구매 옵션·포토 여부용 난수(options.py). 없으면 rng 를 쓴다
    """
    p = spec.product
    order_id = order.order_id if order else None
    review_id = f"R-{seeded_uuid(rng).hex[:12]}"
    created_at = spec.created_at.isoformat()

    review = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(seeded_uuid(rng)),  # 전송 단위 고유 ID (중복 제거용)
        "event_type": "review_created",
        "review_id": review_id,
        "created_at": created_at,
        # 어떤 주문의 리뷰인지. 주문 모드(--source orders)에서만 값이 있고, 무작위 모드는 null.
        # 결제 데이터와 리뷰를 레이크에서 조인할 때 쓴다.
        "order_id": order_id,
        # [임시] 아래 3개는 나중에 order·상품 테이블에서 가져온다 (주문 모드에서는 product_id 가 주문 값)
        # category 는 실제 상품 데이터에서 받지 않으면 null 이다(2026-10-16, catalog.py)
        "product_id": p.product_id,
        "product_name": p.product_name,
        "category": p.category,
        # [임시] 구매 옵션 사이즈·색상, 포토 리뷰 여부 (options.py, 2026-10-14 확정). 나중에 주문 데이터에서
        # 상품 정보에 색상이 있으면 option_color 는 그 색 (catalog.py, 2026-10-16)
        # category 가 없는 상품은 상품 종류로 사이즈 묶음을 고른다
        **pick_options(
            p.category, attr_rng or rng, p.info.get("color"), p.info.get("product_type")
        ),
        "member_id": spec.member_id,  # 주문 모드에서는 주문의 member_id
        # 구매(결제) 시각. 주문 모드에서만 값이 있다 (2026-10-14 확정)
        "purchased_at": order.paid_at.isoformat() if order else None,
        # [임시] 나중에 member 테이블에서 member_id 와 같이 가져온다
        "age_group": spec.age_group,
        "rating": spec.rating,
        "text": generated["text"],
        "source": "simulator",
        # 실제로 내보낸 시각(UTC). 과거 날짜를 만들면 created_at 과 달라진다 (2026-10-14 확정).
        # 실행할 때마다 바뀌는 유일한 칸이라, 재현성 비교는 이 칸을 빼고 한다.
        "emitted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }

    truth = {
        "schema_version": TRUTH_SCHEMA_VERSION,
        "review_id": review_id,  # 리뷰 이벤트와 연결하는 키
        "order_id": order_id,
        "created_at": created_at,
        "product_id": p.product_id,
        "category": p.category,
        "rating": spec.rating,
        "text": generated["text"],
        # 정답 라벨 (p5.4): 명세 속성 + 검수 모델이 찾은 추가 속성. 각 원소의 source 가 "spec" / "verifier".
        # 가짜 생성기(--llm fake)는 검수가 없어서 명세 그대로(source 없음). 명세 속성만 보려면 spec_aspects.
        "aspects": generated.get("truth_aspects") or spec.aspects,
        "spec_aspects": spec.aspects,
        # 이상 상황(incidents.json)으로 만든 리뷰면 그 ID, 아니면 null → 이상탐지 채점용
        "incident_id": spec.incident_id,
        # 어떤 모델·프롬프트로 만들었는지 (품질 비교·재생성 판단용)
        "generator": {
            "model_id": model_id,
            "prompt_version": PROMPT_VERSION,
            # 프롬프트 예시 세트 버전 (data/examples/ex-vN.md, 설정 EXAMPLES_VERSION). 예시 버전별 성능 비교용
            "examples_version": examples_version,
            "style": spec.style,
            "length": spec.length,
        },
    }
    return review, truth


def make_order_source(
    source: str, settings, orders_path: Path, timing: ReviewTiming, start: datetime, end: datetime
) -> OrderSource:
    """주문을 읽을 곳을 고른다.

    orders : 로컬 JSONL 주문 파일 (가짜 주문, 예전 방식)
    rds    : RDS orders 테이블. 리뷰 시각이 [start, end) 에 떨어질 수 있는 결제만 읽는다
             → 결제 시각 [start - 최대 텀, end - 최소 텀). 경계에서 빠지지 않게 앞뒤로 하루씩 여유를 둔다
               (텀은 초 단위라 정확히 잘라도 되지만, 여유를 둬도 due_orders 가 다시 거르므로 결과는 같다)
    """
    if source == "rds":
        since = start - timedelta(days=timing.max_days + 1)
        until = end - timedelta(days=max(timing.min_days - 1, 0))
        return RdsOrderSource(settings.orders_database_url, since, until)
    return JsonlOrderSource(orders_path)


def _order_specs(
    engine: ScenarioEngine,
    catalog: Catalog,
    settings,
    orders_path: Path,
    day: date,
    limit: int,
    source: str = "orders",
    order_source: OrderSource | None = None,
) -> list[tuple[ReviewSpec, Order]]:
    """주문 모드: 리뷰 시각이 날짜 day(UTC) 하루 안에 떨어지는 주문을 골라 (명세, 주문) 목록을 만든다.

    1) 주문을 읽는다 (source=orders: JSONL 파일 / source=rds: RDS orders 테이블, make_order_source)
       order_source 를 주면 그것을 쓴다(테스트에서 가짜 DB 를 넣을 때)
    2) 결제 시각 + 텀(1~7일)이 [day 00:00 UTC, 다음 날 00:00 UTC) 안인 주문만 남긴다 (orders.due_orders)
    3) 상품: 주문에 RDS 상품 정보가 있으면 그것을, 없으면 상품 목록(catalog)에서 찾는다.
       상품 목록에도 없는 상품의 주문은 건너뛰고 건수만 로그에 남긴다
    4) 연령대: 주문에 RDS 회원 연령대가 있으면 그것을, 없으면 무작위(scenario.AGE_GROUP_WEIGHTS)
    limit > 0 이면 리뷰 시각이 빠른 순서로 그 수만큼만 만든다(--sink lake 면 그날 파티션에 그만큼만 남는다).
    날짜는 UTC 기준이다. 레이크의 dt 파티션(Bronze = UTC)과 같은 경계로 잘라야 한 번 실행 = 파티션 하나가 된다.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)
    timing = ReviewTiming(
        rate=settings.review_rate,
        min_days=settings.review_delay_min_days,
        max_days=settings.review_delay_max_days,
    )
    if order_source is None:
        order_source = make_order_source(source, settings, orders_path, timing, start, end)
    orders = order_source.load()
    due = due_orders(orders, timing, start, end)

    todo: list[tuple[ReviewSpec, Order]] = []
    unknown = 0
    for order, due_at in due:
        product = order.product or catalog.by_id.get(order.product_id)
        if product is None:
            unknown += 1
            continue
        todo.append(
            (engine.spec_for_order(product, due_at, order.member_id, order.age_group), order)
        )
        if limit and len(todo) >= limit:
            break
    log.info(
        "주문 %d건 중 %s(UTC)에 리뷰 시각이 있는 주문 %d건, 이번에 만들 %d건",
        len(orders),
        day.isoformat(),
        len(due),
        len(todo),
    )
    if unknown:
        log.warning("상품 목록에 없는 product_id 주문 %d건은 건너뜀 (catalog.py 참고)", unknown)
    return todo


def make_sink(kind: str, settings, out_path: Path):
    if kind == "kafka":
        return KafkaSink(
            settings.kafka_bootstrap,
            settings.kafka_topic,
            settings.kafka_truth_topic,
            settings.kafka_partitions,
        )
    if kind == "lake":
        # S3 레이크 경로 구조 (지금은 로컬 폴더 LAKE_ROOT). dt 파티션을 덮어쓴다
        return LakeSink(settings.lake_root, settings.lake_truth_root, settings.aws_region)
    if kind == "jsonl":
        # 정답은 같은 폴더의 <이름>_truth.jsonl 에 따로 저장 (예: reviews.jsonl / reviews_truth.jsonl)
        return JsonlSink(out_path, out_path.with_name(out_path.stem + "_truth" + out_path.suffix))
    return StdoutSink()


def run(
    *,
    llm: str = "bedrock",
    sink_kind: str = "stdout",
    source: str = "random",
    count: int | None = None,
    max_rps: float = 0.0,
    start: datetime | None = None,
    reviews_per_hour: float = 20.0,
    out: Path = Path(".local/out/reviews.jsonl"),
    batch_size: int | None = None,
    orders_path: Path | None = None,
    day: date | None = None,
    order_source: OrderSource | None = None,
) -> int:
    """리뷰를 만들어 전송한다. 반환: 전송한 리뷰 수. 인자 설명은 cli.py 의 rsim run 도움말과 같다.

    source
      random : 가상 시계 + 무작위 상품으로 리뷰를 만든다 (예전 방식). count 기본 10, 0 이면 계속.
      orders : 주문 파일에서 "리뷰 시각(결제 + 1~7일)이 날짜 day(UTC) 안인 주문"을 골라 리뷰를 만든다.
               day 기본 = 어제(UTC, 다 끝난 마지막 하루). count 기본 0 = 그날 주문 전부.
      rds    : orders 와 같지만 주문을 RDS orders 테이블에서 읽는다(주문 항목 하나 = 리뷰 하나,
               상품 정보·회원 연령대도 RDS 값). 접속 주소는 ORDERS_DATABASE_URL.
    order_source : 테스트용. 주문을 읽을 곳을 직접 넣는다(가짜 DB 등)
    """
    settings = load_settings()
    batch_size = batch_size or settings.batch_size
    seed = resolve_seed(settings.random_seed)
    # 용도별로 난수열을 나눈다. 시드 표본·상품·명세·ID 가 서로의 난수 소비에 영향을 주지 않게.
    rng = make_rng(derive_seed(seed, "review"))
    id_rng = make_rng(derive_seed(seed, "ids"))
    # 구매 옵션·포토 여부용 (2026-10-14 추가). 따로 나눠서 기존 명세·ID 순서가 바뀌지 않게 한다
    attr_rng = make_rng(derive_seed(seed, "attrs"))

    # ---- 준비: 시드 → 상품 → 이상 상황 → 명세 엔진 → 생성기 → 전송처
    seeds = SeedPool.load(settings.seeds_path, rng)
    order_mode = source in ("orders", "rds")
    if order_mode:
        # 주문 모드는 상품 목록을 RANDOM_SEED 와 무관한 고정 난수로 만든다.
        # rsim orders-fake 와 같은 상품 목록(같은 product_id → 같은 상품명)이 나와야 주문과 이어지기 때문이다.
        catalog = Catalog.build(settings.products_path, seeds.product_names(), catalog_rng())
    else:
        catalog = Catalog.build(settings.products_path, seeds.product_names(), rng)
    incidents = load_incidents(settings.incidents_path)
    engine = ScenarioEngine(
        catalog, incidents, SimClock(start, reviews_per_hour, rng), rng, id_rng=id_rng
    )
    generator = make_generator(settings, seeds) if llm == "bedrock" else FakeGenerator(rng)
    sink = make_sink(sink_kind, settings, out)

    log.info(
        "시드 %d건, 상품 %d개, 이상 상황 %d개, 모델=%s, 입력=%s, 전송=%s, RANDOM_SEED=%d",
        len(seeds.rows),
        len(catalog.products),
        len(incidents),
        generator.model_id,
        source,
        sink_kind,
        seed,
    )

    # ---- 만들 명세 목록 정하기
    # random : 필요할 때마다 engine.next_spec() 으로 하나씩 만든다 (todo = None)
    # orders : 그날 주문을 미리 골라 (명세, 주문) 목록으로 만들어 둔다
    todo: list[tuple[ReviewSpec, Order]] | None = None
    if order_mode:
        day = day or (datetime.now(UTC) - timedelta(days=1)).date()
        todo = _order_specs(
            engine,
            catalog,
            settings,
            orders_path or settings.orders_path,
            day,
            count or 0,
            source=source,
            order_source=order_source,
        )
        count = len(todo)
        if count == 0:
            log.info("이 날짜에 리뷰를 쓸 주문이 없습니다")
            sink.close()
            return 0
    elif count is None:
        count = 10

    # Ctrl+C(SIGINT) / ECS 종료 신호(SIGTERM)를 받으면 현재 배치까지만 보내고 깔끔하게 끝낸다
    stop = {"flag": False}

    def _handle_stop(signum, frame):
        log.info("종료 신호 수신: 현재 배치를 마치고 종료합니다")
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    produced = skipped = 0
    started = time.monotonic()
    try:
        while not stop["flag"] and (count == 0 or produced < count):
            if todo is None:
                n = batch_size if count == 0 else min(batch_size, count - produced)
                batch = [(engine.next_spec(), None) for _ in range(n)]
            else:
                # 주문 모드: 앞에서부터 batch_size 개씩. 실패한 주문은 리뷰가 없으니 다음 실행에서 다시 골라진다
                if not todo:
                    break
                batch, todo = todo[:batch_size], todo[batch_size:]
            specs = [spec for spec, _ in batch]
            results = generator.generate(specs)

            for spec, order in batch:
                gen = results.get(spec.spec_id)
                if not gen or not gen.get("text"):
                    # 생성 실패/검수 탈락한 명세는 버린다 (다음 배치에서 새 명세로 채워짐)
                    skipped += 1
                    continue
                # 주문 모드는 ID·옵션을 order_id 로 정한다(같은 날짜를 다시 돌려도 같은 값)
                # RDS 주문은 주문 항목 ID(Order.key)로 정한다(한 주문에 상품이 여러 개면 상품마다 다른 ID)
                if order:
                    ids = order_id_rng(order.key)
                    attrs = order_id_rng(order.key, "review-attrs")
                else:
                    ids, attrs = id_rng, attr_rng
                review, truth = build_events(
                    spec,
                    gen,
                    generator.model_id,
                    ids,
                    order,
                    attrs,
                    # 가짜 생성기는 예시를 안 쓰므로 None
                    examples_version=getattr(generator, "examples_version", None),
                )
                sink.send(review, truth)
                produced += 1

                # 실제 전송 속도 제한: 지금까지 보낸 수 / 경과 시간이 max_rps 를 넘지 않게 잠깐 쉰다
                if max_rps > 0:
                    ahead = produced / max_rps - (time.monotonic() - started)
                    if ahead > 0:
                        time.sleep(ahead)

            log.info("진행: 전송 %d건, 건너뜀 %d건", produced, skipped)
    finally:
        sink.close()
        u = generator.usage
        log.info(
            "끝: 전송 %d건, 건너뜀 %d건, 모델 호출 %d회, 입력 토큰 %d, 출력 토큰 %d",
            produced,
            skipped,
            u["calls"],
            u["input_tokens"],
            u["output_tokens"],
        )
        # 검수 루프 통계 (Bedrock 생성기만 있음): 검사 건수, 1차 실패, 재생성 후에도 실패해서 버린 건수
        stats = getattr(generator, "aspect_stats", None)
        if stats:
            log.info(
                "검수: %d건 중 1차 실패 %d건, 버림 %d건, 정답 라벨에 속성 추가 %d건",
                stats["checked"],
                stats["failed_first"],
                stats["dropped"],
                stats.get("extra_added", 0),
            )
        if u.get("verify_calls"):
            log.info(
                "검수 호출 %d회, 입력 토큰 %d, 출력 토큰 %d",
                u["verify_calls"],
                u["verify_input_tokens"],
                u["verify_output_tokens"],
            )
    return produced
