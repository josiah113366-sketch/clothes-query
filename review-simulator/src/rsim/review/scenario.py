"""리뷰 명세(spec) 만들기 + 이상 상황(incident) 주입 + 시뮬레이션 시계.

LLM 에게 "아무 리뷰나 써 줘"라고 하면 별점·속성 분포를 통제할 수 없다.
그래서 **무엇을 쓸지는 코드가 정하고(명세), 어떻게 쓸지(문장)만 LLM 에 맡긴다.**
덕분에 모든 리뷰에 정답 라벨(속성·감성)이 붙고, 이상 상황도 원하는 대로 넣을 수 있다.

명세 예
-------
ReviewSpec(product=W-0003 니트, rating=2,
           aspects=[사이즈·핏:부정, 배송:긍정], style="짧은 반말체", length="short",
           incident_id=None)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..common.rng import make_rng, seeded_uuid
from .catalog import Catalog, Product
from .taxonomy import ASPECT_WEIGHTS, PROS_CONS_STYLE, REBUY_STYLE, REBUY_STYLE_RATE, STYLES

# ---------------------------------------------------------------- 별점 분포
# 실제 쇼핑몰처럼 5점이 많고 1점이 2점보다 조금 많은 'J자' 분포.
# (AI Hub 쇼핑몰 ReviewScore 분포: 100점이 약 66%)
# 순서대로 1점, 2점, 3점, 4점, 5점의 상대 비율.
RATING_WEIGHTS = [0.07, 0.05, 0.10, 0.20, 0.58]

# 별점별로 각 속성 감성이 (긍정, 중립, 부정)으로 나올 확률.
# 예: 5점 리뷰는 대부분 긍정 속성이지만 가끔 "다 좋은데 배송이 느려요" 같은 부정이 섞인다.
# 2026-10-16 lemin 결정: 중립은 전체 속성의 약 5% 만 나오게 줄인다 (예전 값 기준 약 13%).
#   예전 값: 1점 (0.03, 0.07, 0.90) / 2점 (0.10, 0.15, 0.75) / 3점 (0.30, 0.40, 0.30)
#            4점 (0.70, 0.18, 0.12) / 5점 (0.90, 0.07, 0.03)
#   별점별 중립을 약 0.4배로 줄이고, 줄인 만큼은 그 별점의 긍정·부정 비율대로 나눠 줬다(별점 방향은 그대로).
#   실제 비율은 별점 분포·상품 품질 편차에 따라 달라진다. 2만 건 시험 결과 속성 기준 중립 약 5%.
#   중립 비율을 다시 바꾸려면 가운데 숫자만 바꾸고 세 숫자 합을 1 로 맞춘다.
SENTIMENT_BY_RATING = {
    1: (0.03, 0.03, 0.94),
    2: (0.11, 0.06, 0.83),
    3: (0.42, 0.16, 0.42),
    4: (0.79, 0.07, 0.14),
    5: (0.94, 0.03, 0.03),
}

# 한 리뷰에 들어갈 속성 개수 분포: 1개, 2개, 3개의 상대 비율
ASPECT_COUNT_WEIGHTS = [0.45, 0.40, 0.15]

# [임시] 리뷰 작성자 연령대 분포. 나중에 member 테이블에서 member_id 와 함께 가져온다(2026-10-13 결정).
# 패션몰 이용자 분포를 대략 가정한 값(20~30대 중심). 순서대로 상대 비율.
AGE_GROUP_WEIGHTS = {
    "10대": 0.05,
    "20대": 0.30,
    "30대": 0.32,
    "40대": 0.20,
    "50대": 0.10,
    "60대 이상": 0.03,
}

# 리뷰 길이: short(한 문장 내외), medium(2~3문장), long(4~6문장)의 상대 비율
LENGTH_WEIGHTS = {"short": 0.5, "medium": 0.38, "long": 0.12}
# p5.2: 짧은 리뷰(한 문장, 40자 이내)는 속성을 최대 2개만 준다.
# p5.1 점검에서 짧은 리뷰 + 속성 3개 조합은 모델이 속성을 빼거나 길이를 넘겼다. 실제 짧은 리뷰도 1~2개가 대부분.
MAX_ASPECTS_SHORT = 2
# p5.4 (lemin 결정): 냄새는 실제 리뷰에서 거의 불만일 때만 나온다("새 신발 냄새 좋아요"는 어색).
# 냄새가 긍정으로 뽑히면 이 확률만 남기고, 나머지는 냄새 대신 다른 속성을 긍정으로 바꾼다.
SMELL_POSITIVE_KEEP = 0.05


@dataclass
class ReviewSpec:
    spec_id: str  # 배치 안에서 LLM 응답과 명세를 짝지을 때 쓰는 짧은 ID
    product: Product
    rating: int
    aspects: list[dict]  # [{"aspect": "사이즈·핏", "sentiment": "부정"}, ...]
    style: str
    length: str
    created_at: datetime  # 시뮬레이션 시각(리뷰 작성 시각으로 기록됨)
    incident_id: str | None = None  # 이상 상황 때문에 만들어진 리뷰면 그 ID (정답 확인용)
    # [임시] 무작위 회원 ID. 나중에 order 테이블의 member_id 로 바꾼다(2026-10-13 결정).
    # 기본값은 테스트용이고, ScenarioEngine 은 시드 고정 난수로 만든 값을 넣는다.
    member_id: str = "C-0000000000"
    # [임시] 작성자 연령대. 나중에 member 테이블에서 member_id 와 같이 가져온다(2026-10-13 결정).
    # 프롬프트에도 넣어서 연령대에 어울리는 말투가 나오게 한다(예: 20대는 줄임말, 50대는 정중체가 조금 더 많게).
    age_group: str = "30대"


# ---------------------------------------------------------------- 이상 상황
@dataclass
class Incident:
    """특정 기간 동안 특정 상품(또는 카테고리)에 특정 속성 불만이 몰리는 상황.

    incidents.json 예:
    [
      {"id": "INC-001", "product_id": "W-0003", "aspect": "품질·내구성", "sentiment": "부정",
       "start": "2026-10-14T00:00:00+09:00", "end": "2026-10-16T00:00:00+09:00",
       "share": 0.6, "volume_multiplier": 3.0, "note": "봉제 불량 로트 입고"}
    ]
    - product_id 대신 "category": "패션슈즈" 를 쓰면 카테고리 전체에 적용
    - share: 해당 상품 리뷰 중 이 불만이 들어가는 비율 (0~1)
    - volume_multiplier: 해당 상품 리뷰 수 자체를 몇 배로 늘릴지 (불만 리뷰가 몰리는 효과). 1이면 그대로
    - start/end 가 없으면 항상 적용
    """

    id: str
    aspect: str
    sentiment: str = "부정"
    product_id: str | None = None
    category: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    share: float = 0.6
    volume_multiplier: float = 1.0
    note: str = ""

    def active(self, now: datetime) -> bool:
        return (self.start is None or now >= self.start) and (self.end is None or now < self.end)

    def matches(self, product: Product) -> bool:
        if self.product_id:
            return product.product_id == self.product_id
        if self.category:
            return product.category == self.category
        return True


def load_incidents(path: Path | str) -> list[Incident]:
    """incidents JSON 을 읽는다. 로컬 파일이 없으면 이상 상황 없음([]).

    s3://버킷/키 도 읽는다(ECS 태스크 역할 권한, 2026-10-18 sim/review-ecs). S3 는 파일이 없으면 오류로 멈춘다
    (일부러 경로를 준 실행이라, 조용히 평소 리뷰만 만들면 시험 결과를 잘못 읽게 된다).
    """
    if isinstance(path, str) and path.startswith("s3://"):
        from .sinks import s3_client

        bucket, _, key = path[len("s3://") :].partition("/")
        text = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8-sig")
    else:
        path = Path(path)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    incidents = []
    for r in raw:
        for key in ("start", "end"):
            if r.get(key):
                r[key] = datetime.fromisoformat(r[key])
        incidents.append(Incident(**r))
    return incidents


# ---------------------------------------------------------------- 시뮬레이션 시계
class SimClock:
    """리뷰 작성 시각(created_at)을 만들어 주는 가상 시계.

    - realtime 모드(start=None): 실제 현재 시각을 그대로 쓴다. (실시간 스트림처럼 보임)
    - backfill 모드(start 지정): 시작 시각부터 '시간당 평균 리뷰 수'에 맞춰 포아송 간격으로 시계를 앞으로 민다.
      예) --start 2026-10-01 --reviews-per-hour 20 → 리뷰 480건이면 약 하루치 데이터가 만들어진다.
      과거 며칠치 데이터를 빠르게 만들어 이상탐지(일별 추세)를 시험할 때 쓴다.
    """

    def __init__(self, start: datetime | None, reviews_per_hour: float, rng: random.Random):
        self.now = start
        self.rate_per_sec = reviews_per_hour / 3600.0
        self.rng = rng

    def tick(self) -> datetime:
        if self.now is None:
            return datetime.now(UTC)
        # 지수분포 간격 = 포아송 도착 과정 (리뷰가 일정 간격이 아니라 들쭉날쭉 들어오게)
        self.now = self.now + timedelta(seconds=self.rng.expovariate(self.rate_per_sec))
        return self.now

    def current(self) -> datetime:
        return self.now or datetime.now(UTC)


# ---------------------------------------------------------------- 명세 생성기
def pick_style(aspects: list[dict], rng: random.Random) -> str:
    """명세의 말투를 고른다 (p5.8, 2026-10-16 lemin 결정).

    1) REBUY_STYLE_RATE(약 30%) 확률로 "재구매 여부를 언급하는 말투"
    2) 아니면 나머지 말투 중에서 똑같은 확률로. 단 "장점과 단점을 나눠서 정리하는 말투"는
       속성에 긍정과 부정이 둘 다 있을 때만 후보에 넣는다(없는 단점·장점을 지어내지 않게).
    """
    if rng.random() < REBUY_STYLE_RATE:
        return REBUY_STYLE
    sentiments = {a["sentiment"] for a in aspects}
    mixed = {"긍정", "부정"} <= sentiments
    others = [s for s in STYLES if s != REBUY_STYLE and (mixed or s != PROS_CONS_STYLE)]
    return rng.choice(others)


class ScenarioEngine:
    def __init__(
        self,
        catalog: Catalog,
        incidents: list[Incident],
        clock: SimClock,
        rng: random.Random,
        id_rng: random.Random | None = None,
    ):
        self.catalog = catalog
        self.incidents = incidents
        self.clock = clock
        self.rng = rng
        # 회원 ID 는 별도 난수열로 만든다. 명세용 rng 에서 뽑으면 같은 시드의 예전 명세 순서가 바뀐다.
        self.id_rng = id_rng or make_rng(0)
        self._counter = 0

    def _pick_product(self, now: datetime) -> Product:
        """상품을 고른다. 진행 중인 이상 상황이 volume_multiplier > 1 이면 그 상품이 더 자주 뽑힌다."""
        product = self.catalog.pick()
        for inc in self.incidents:
            if not (inc.active(now) and inc.volume_multiplier > 1):
                continue
            targets = [p for p in self.catalog.products if inc.matches(p)]
            if not targets or inc.matches(product):
                continue
            # 계산 방법
            #   s  = 평소 대상 상품이 뽑히는 비율 (대략 대상 상품 수 / 전체 상품 수)
            #   m  = volume_multiplier
            #   s' = 대상 상품 리뷰 수가 m 배가 됐을 때의 비율 = m*s / (1 + (m-1)*s)
            # 대상이 아닌 상품이 뽑혔을 때 q 확률로 대상 상품으로 바꾸면 비율이 s' 가 된다.
            #   q = (s' - s) / (1 - s)
            s = len(targets) / len(self.catalog.products)
            m = inc.volume_multiplier
            s_new = m * s / (1 + (m - 1) * s)
            q = (s_new - s) / (1 - s) if s < 1 else 0
            if self.rng.random() < q:
                product = self.rng.choice(targets)
        return product

    def _pick_rating(self, product: Product) -> int:
        """기본 별점 분포에 상품 품질 편차(quality_bias)를 더해 별점을 고른다."""
        base = self.rng.choices([1, 2, 3, 4, 5], weights=RATING_WEIGHTS)[0]
        shifted = round(base + product.quality_bias * self.rng.random())
        return max(1, min(5, shifted))

    def _demote_smell(self, aspects: list[dict]) -> list[dict]:
        """냄새:긍정을 SMELL_POSITIVE_KEEP 확률만 남기고, 나머지는 아직 없는 다른 속성:긍정으로 바꾼다.
        별점 맞추기·짧은 리뷰 자르기 뒤에도 냄새가 긍정이 될 수 있어서, 명세를 다 만든 뒤 마지막에 한 번 부른다."""
        for a in aspects:
            if (
                a["aspect"] == "냄새"
                and a["sentiment"] == "긍정"
                and self.rng.random() >= SMELL_POSITIVE_KEEP
            ):
                used = {x["aspect"] for x in aspects}
                others = [x for x in ASPECT_WEIGHTS if x not in used]
                a["aspect"] = self.rng.choices(others, weights=[ASPECT_WEIGHTS[x] for x in others])[
                    0
                ]
        return aspects

    def _pick_aspects(self, rating: int, n: int) -> list[dict]:
        names = list(ASPECT_WEIGHTS)
        chosen: list[str] = []
        while len(chosen) < n:
            a = self.rng.choices(names, weights=[ASPECT_WEIGHTS[x] for x in names])[0]
            if a not in chosen:
                chosen.append(a)
        probs = SENTIMENT_BY_RATING[rating]
        aspects = [
            {"aspect": a, "sentiment": self.rng.choices(["긍정", "중립", "부정"], weights=probs)[0]}
            for a in chosen
        ]
        # 별점과 정반대인 리뷰 방지: 4~5점인데 속성이 전부 부정이거나, 1~2점인데 전부 긍정이면
        # 첫 번째 속성을 별점 방향으로 바꾼다. (예: 5점짜리 "품질 별로, 사이즈 별로" 같은 어색한 리뷰 제거)
        sentiments = {a["sentiment"] for a in aspects}
        if rating >= 4 and sentiments == {"부정"}:
            aspects[0]["sentiment"] = "긍정"
        elif rating <= 2 and sentiments == {"긍정"}:
            aspects[0]["sentiment"] = "부정"
        return aspects

    def next_spec(self) -> ReviewSpec:
        """무작위 모드(rsim run 기본): 가상 시계로 시각을 정하고 상품도 무작위로 고른다."""
        now = self.clock.tick()
        product = self._pick_product(now)
        return self._build_spec(now, product)

    def spec_for_order(
        self,
        product: Product,
        created_at: datetime,
        member_id: str,
        age_group: str | None = None,
    ) -> ReviewSpec:
        """주문 모드(rsim run --source orders): 상품·작성 시각·회원은 주문에서 정해진 값을 쓴다.

        나머지(별점·속성·말투·길이·이상 상황)는 무작위 모드와 같은 규칙으로 정한다.
        상품이 주문으로 정해지므로 이상 상황의 volume_multiplier(리뷰 수 늘리기)는 적용되지 않고,
        share(해당 상품 리뷰에 불만을 넣는 비율)만 적용된다. 리뷰 수를 늘리려면 주문 쪽에서 늘려야 한다.

        age_group 을 주면(RDS 회원 연령대, --source rds) 그 값을 쓴다. 이때도 무작위 연령대 난수는 그대로 뽑고
        결과만 바꿔 끼운다 → 다른 명세 값(별점·속성 등)의 난수 순서가 연령대 유무에 따라 달라지지 않는다.
        """
        spec = self._build_spec(created_at, product, member_id=member_id)
        if age_group:
            spec = replace(spec, age_group=age_group)
        return spec

    def _build_spec(
        self, now: datetime, product: Product, member_id: str | None = None
    ) -> ReviewSpec:
        # 난수를 뽑는 순서는 예전 next_spec 과 같게 둔다(같은 시드면 예전과 같은 명세가 나온다)
        rating = self._pick_rating(product)
        n_aspects = self.rng.choices([1, 2, 3], weights=ASPECT_COUNT_WEIGHTS)[0]
        aspects = self._pick_aspects(rating, n_aspects)
        incident_id = None

        # 진행 중인 이상 상황이 이 상품에 해당하면, share 확률로 해당 속성 불만을 강제로 넣는다.
        for inc in self.incidents:
            if inc.active(now) and inc.matches(product) and self.rng.random() < inc.share:
                aspects = [a for a in aspects if a["aspect"] != inc.aspect]
                aspects.insert(0, {"aspect": inc.aspect, "sentiment": inc.sentiment})
                aspects = aspects[:3]
                if inc.sentiment == "부정":
                    # 불만이 핵심인 리뷰는 별점도 낮게 (1~3점)
                    rating = min(rating, self.rng.choice([1, 2, 2, 3]))
                incident_id = inc.id
                break

        # p5.8: 말투는 속성이 다 정해진 뒤에 고른다(장단점 말투는 긍정·부정이 섞였을 때만이라서).
        # 그래서 같은 시드라도 p5.7 까지와는 다른 명세가 나온다.
        length = self.rng.choices(list(LENGTH_WEIGHTS), weights=list(LENGTH_WEIGHTS.values()))[0]
        if length == "short" and len(aspects) > MAX_ASPECTS_SHORT:
            # 앞쪽(이상 상황 속성이 있으면 그게 맨 앞)만 남긴다. 줄인 뒤에도 별점과 정반대가 되지 않게 다시 맞춘다.
            aspects = aspects[:MAX_ASPECTS_SHORT]
            sentiments = {a["sentiment"] for a in aspects}
            if rating >= 4 and sentiments == {"부정"} and incident_id is None:
                aspects[0]["sentiment"] = "긍정"
            elif rating <= 2 and sentiments == {"긍정"}:
                aspects[0]["sentiment"] = "부정"

        aspects = self._demote_smell(aspects)
        style = pick_style(aspects, self.rng)

        self._counter += 1
        return ReviewSpec(
            spec_id=f"s{self._counter}",
            product=product,
            rating=rating,
            aspects=aspects,
            style=style,
            length=length,
            created_at=now,
            incident_id=incident_id,
            age_group=self.rng.choices(
                list(AGE_GROUP_WEIGHTS), weights=list(AGE_GROUP_WEIGHTS.values())
            )[0],
            # 주문 모드는 주문의 member_id 를 쓰고, 무작위 모드는 [임시] 시드 고정 무작위 값을 만든다
            member_id=member_id or f"C-{seeded_uuid(self.id_rng).hex[:10]}",
        )
