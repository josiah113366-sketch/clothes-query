"""상품 목록.

리뷰 이벤트에는 어떤 상품의 리뷰인지(product_id)가 꼭 들어가야 한다.
이상탐지가 "상품별·속성별 불만이 갑자기 늘었는가"를 보기 때문이다.

상품 목록을 정하는 순서
1. data/products.csv 가 있으면 그것을 쓴다 (CsvProductSource).
   필수 컬럼: product_id, product_name
   선택 컬럼: 상품 정보(PRODUCT_INFO_FIELDS). 값이 있으면 리뷰 생성 프롬프트에 함께 들어간다(p5.7).
   category 는 받지 않아도 된다(2026-10-16 lemin: 상품 정보만 있으면 리뷰를 쓰는 데 문제없음).
     컬럼이 있고 값이 taxonomy.CATEGORIES 4개 중 하나면 쓰고, 아니면 None 으로 둔다.
     category 가 None 이면 리뷰의 category 칸은 null, 사이즈 옵션은 상품 종류로 추정한다(options.size_group_of).
   → 나중에 H&M 상품 마스터(article_id, prod_name, ...)를 이 형식으로 뽑아 넣으면
     결제/회원 시뮬레이터와 같은 상품 ID 로 두 흐름이 연결된다.
     H&M 컬럼 이름(article_id, prod_name, colour_group_name, detail_desc 등)은 그대로 넣어도 읽는다(COLUMN_ALIASES).
2. 없으면 시드(AI Hub)의 상품명으로 카테고리별 N개씩 가짜 상품을 만든다. (상품 정보 없음 → 프롬프트는 예전과 같은 내용)

상품 정보는 **프롬프트에만** 쓰고 리뷰 이벤트 컬럼(review.v2)은 늘리지 않는다(2026-10-16 lemin 확인).
리뷰와 상품 정보를 같이 보려면 레이크에서 product_id 로 상품 테이블과 조인한다.
단, 상품에 색상이 있으면 리뷰의 option_color 를 그 색으로 맞춘다(options.py).

나중에 S3 상품 테이블에서 읽을 때는 ProductSource 와 같은 모양(load() → list[Product])의 클래스를 만들어
Catalog.build 에 넘기면 된다.
"""

from __future__ import annotations

import csv
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .taxonomy import CATEGORIES

log = logging.getLogger(__name__)

# 상품 정보 칸: 키 → 프롬프트에 보이는 이름. 순서대로 프롬프트에 들어간다.
# 칸을 더하려면 여기에 한 줄 더하고(필요하면 COLUMN_ALIASES 에 원본 컬럼 이름도), 프롬프트 규칙 13(generator.py)을 확인한다.
PRODUCT_INFO_FIELDS: dict[str, str] = {
    "product_type": "상품 종류",  # 예: 셔츠, 니트, 운동화
    "material": "소재",  # 예: 면 100%, 린넨
    "color": "색상",  # 예: 블랙. 리뷰의 option_color 로도 쓴다
    "pattern": "무늬",  # 예: 스트라이프, 무지
    "fit": "핏",  # 예: 오버핏, 슬림핏
    "season": "계절",  # 예: 여름
    "description": "상품 설명",  # 상세 설명 한두 문장. 영어여도 된다(본문은 한국어로 쓰게 지시함)
}

# 다른 이름으로 들어오는 컬럼 → 우리 이름. 왼쪽 컬럼이 있으면 오른쪽 이름으로 읽는다.
# (같은 칸에 두 컬럼이 다 있으면 우리 이름 컬럼을 먼저 쓴다)
COLUMN_ALIASES: dict[str, str] = {
    # H&M articles.csv
    "article_id": "product_id",
    "prod_name": "product_name",
    "product_type_name": "product_type",
    "colour_group_name": "color",
    "graphical_appearance_name": "pattern",
    "detail_desc": "description",
}

# 상품 정보 값이 너무 길면 프롬프트 토큰만 늘어나서 자른다(글자 수). 설명 한두 문장이면 충분하다.
MAX_INFO_CHARS = 200

# products.csv 가 없을 때 카테고리별로 만들 가짜 상품 수.
# 상품이 너무 많으면 상품당 리뷰가 적어 이상탐지 테스트가 어려워지므로 적게 둔다.
DEFAULT_PRODUCTS_PER_CATEGORY = 10

# 카테고리별 상품 ID 접두사 (예: W-0003 = 여성의류 3번 상품)
CATEGORY_CODES = {"여성의류": "W", "남성의류": "M", "패션슈즈": "S", "잡화": "A"}

# 카테고리별로 리뷰가 달리는 상대 비율(AI Hub 쇼핑몰 데이터의 카테고리 비율과 비슷하게)
CATEGORY_WEIGHTS = {"여성의류": 0.43, "남성의류": 0.22, "패션슈즈": 0.26, "잡화": 0.09}


@dataclass
class Product:
    product_id: str
    product_name: str
    category: str | None  # 4개 카테고리 중 하나, 실제 상품 데이터에서는 None 일 수 있다(위 설명)
    # 상품마다 고정된 "기본 만족도" 편차. +면 좋은 상품(별점이 높게), -면 나쁜 상품.
    # scenario.py 가 별점을 뽑을 때 사용. 상품마다 평균 별점이 조금씩 다르게 보이게 하려는 장치.
    quality_bias: float = 0.0
    # 상품 정보 (PRODUCT_INFO_FIELDS 의 키 → 값). 값이 있는 칸만 들어 있다. 비어 있으면 프롬프트에 안 넣는다.
    info: dict[str, str] = field(default_factory=dict)


class ProductSource(Protocol):
    """상품을 읽어 오는 곳. 지금은 CsvProductSource 하나, 나중에 S3 상품 테이블용을 추가한다."""

    def load(self) -> list[Product]: ...


def _clean(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


class CsvProductSource:
    """data/products.csv 를 읽는다. 위 모듈 설명의 컬럼 규칙을 따른다.

    category 는 4개 카테고리 중 하나일 때만 쓰고, 없거나 다른 값(예: H&M 의 Ladieswear)이면 None 이다.
    quality_bias 는 여기서 정하지 않는다(Catalog 가 난수로 채운다).
    """

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[Product]:
        products = []
        with open(self.path, encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                r = {}
                for k, v in raw.items():
                    if k is None:
                        continue
                    key = COLUMN_ALIASES.get(k.strip(), k.strip())
                    # 우리 이름 컬럼이 이미 있으면 별칭 컬럼으로 덮어쓰지 않는다
                    if key in r and k.strip() != key:
                        continue
                    r[key] = _clean(v)
                info = {k: r[k][:MAX_INFO_CHARS] for k in PRODUCT_INFO_FIELDS if r.get(k)}
                products.append(
                    Product(
                        product_id=r["product_id"],
                        product_name=r["product_name"],
                        category=r.get("category") if r.get("category") in CATEGORIES else None,
                        info=info,
                    )
                )
        log.info(
            "상품 %d개 읽음: %s (상품 정보 있음 %d개)",
            len(products),
            self.path,
            sum(bool(p.info) for p in products),
        )
        return products


class Catalog:
    def __init__(self, products: list[Product], rng: random.Random):
        self.products = products
        self.rng = rng
        self.by_id = {p.product_id: p for p in products}

    @classmethod
    def build(
        cls,
        csv_path: Path,
        names_by_category: dict[str, list[str]],
        rng: random.Random,
        source: ProductSource | None = None,
    ) -> Catalog:
        """상품 목록을 만든다. source 를 주면 그것을, 아니면 csv_path 가 있을 때 CsvProductSource 를 쓴다."""
        if source is None and csv_path.exists():
            source = CsvProductSource(csv_path)
        if source is not None:
            products = source.load()
            # 상품마다 기본 만족도 편차를 읽은 순서대로 뽑는다(예전 products.csv 읽기와 같은 난수 순서)
            for p in products:
                p.quality_bias = rng.gauss(0, 0.5)
            return cls(products, rng)

        products = []
        for cat in CATEGORIES:
            names = names_by_category.get(cat) or [f"{cat} 상품"]
            chosen = rng.sample(names, min(DEFAULT_PRODUCTS_PER_CATEGORY, len(names)))
            for i, name in enumerate(chosen, start=1):
                products.append(
                    Product(
                        product_id=f"{CATEGORY_CODES[cat]}-{i:04d}",
                        product_name=name,
                        category=cat,
                        # 표준편차 0.5: 대부분 상품은 평균 근처, 일부만 확실히 좋거나 나쁨
                        quality_bias=rng.gauss(0, 0.5),
                    )
                )
        return cls(products, rng)

    def pick(self, rng: random.Random | None = None) -> Product:
        """카테고리 비율에 맞춰 상품 하나를 고른다. rng 를 주면 그 난수열로 고른다(가짜 주문 만들 때).

        category 가 없는 상품(실제 상품 데이터)은 하나의 묶음으로 보고 가중치 0.1 을 나눠 갖는다.
        모든 상품의 category 가 없으면 결국 상품마다 같은 확률이다.
        카테고리 가중치를 그 카테고리의 상품 수로 나눠서, 상품 수가 많은 카테고리가
        리뷰를 더 많이 가져가지 않게 한다(카테고리 간 비율은 CATEGORY_WEIGHTS 대로 유지).
        """
        counts: dict[str, int] = {}
        for p in self.products:
            counts[p.category] = counts.get(p.category, 0) + 1
        weights = [
            CATEGORY_WEIGHTS.get(p.category, 0.1) / counts[p.category] for p in self.products
        ]
        return (rng or self.rng).choices(self.products, weights=weights)[0]
