"""상품 목록.

리뷰 이벤트에는 어떤 상품의 리뷰인지(product_id)가 꼭 들어가야 한다.
이상탐지가 "상품별·속성별 불만이 갑자기 늘었는가"를 보기 때문이다.

상품 목록을 정하는 순서
1. data/products.csv 가 있으면 그것을 쓴다.
   컬럼: product_id, product_name, category, price(선택)
   → 나중에 H&M 상품 마스터(article_id, prod_name, ...)를 이 형식으로 뽑아 넣으면
     결제/회원 시뮬레이터와 같은 상품 ID 로 두 흐름이 연결된다.
2. 없으면 시드(AI Hub)의 상품명으로 카테고리별 N개씩 가짜 상품을 만든다.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path

from .taxonomy import CATEGORIES

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
    category: str
    # 상품마다 고정된 "기본 만족도" 편차. +면 좋은 상품(별점이 높게), -면 나쁜 상품.
    # scenario.py 가 별점을 뽑을 때 사용. 상품마다 평균 별점이 조금씩 다르게 보이게 하려는 장치.
    quality_bias: float = 0.0


class Catalog:
    def __init__(self, products: list[Product], rng: random.Random):
        self.products = products
        self.rng = rng
        self.by_id = {p.product_id: p for p in products}

    @classmethod
    def build(
        cls, csv_path: Path, names_by_category: dict[str, list[str]], rng: random.Random
    ) -> Catalog:
        if csv_path.exists():
            products = []
            with open(csv_path, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    products.append(
                        Product(
                            product_id=r["product_id"].strip(),
                            product_name=r["product_name"].strip(),
                            category=r["category"].strip(),
                            quality_bias=rng.gauss(0, 0.5),
                        )
                    )
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
