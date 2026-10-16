"""리뷰에 붙는 구매 옵션(사이즈·색상)과 포토 리뷰 여부.

2026-10-14 lemin 확정 컬럼: option_size, option_color, has_photo (+ emitted_at, purchased_at 는 run.py).
[임시] 사이즈·색상은 원래 주문 시 고른 옵션이라 나중에 주문 데이터에서 가져온다. 그 전까지 여기서 만든다.
지금은 프롬프트에 넣지 않는다(리뷰 문장은 옵션과 무관). 문장에 반영하려면 generator.py 프롬프트를 바꾸고
PROMPT_VERSION 을 올려야 한다.

난수는 호출하는 쪽이 넘겨준다(run.py):
  무작위 모드 → RANDOM_SEED 에서 나눈 별도 난수열("attrs")  : 명세·ID 난수열에 영향 없음
  주문 모드   → order_id 로 만든 난수열                    : 같은 날짜를 다시 돌려도 같은 옵션
"""

from __future__ import annotations

import random

# 카테고리별 사이즈 옵션과 상대 비율. 잡화는 사이즈가 없어서 FREE 하나.
# 비율은 패션몰 판매 분포를 대략 가정한 값(가운데 사이즈가 많게). 바꾸려면 여기만 고치면 된다.
SIZE_OPTIONS: dict[str, dict[str, float]] = {
    "여성의류": {"XS": 0.08, "S": 0.27, "M": 0.35, "L": 0.22, "XL": 0.08},
    "남성의류": {"S": 0.10, "M": 0.28, "L": 0.34, "XL": 0.20, "XXL": 0.08},
    # 신발은 mm. 여성·남성 사이즈가 섞인 분포
    "패션슈즈": {
        "225": 0.04,
        "230": 0.08,
        "235": 0.11,
        "240": 0.12,
        "245": 0.09,
        "250": 0.08,
        "255": 0.08,
        "260": 0.12,
        "265": 0.11,
        "270": 0.10,
        "275": 0.05,
        "280": 0.02,
    },
    "잡화": {"FREE": 1.0},
}
# 카테고리를 모를 때(상품 목록에 없는 카테고리) 쓰는 사이즈
DEFAULT_SIZE = "FREE"

# 색상 옵션과 상대 비율 (무채색이 많게)
COLOR_OPTIONS: dict[str, float] = {
    "블랙": 0.30,
    "화이트": 0.15,
    "그레이": 0.11,
    "네이비": 0.11,
    "베이지": 0.10,
    "아이보리": 0.07,
    "브라운": 0.06,
    "카키": 0.05,
    "레드": 0.03,
    "블루": 0.02,
}

# 포토 리뷰 비율 (0~1). 국내 패션몰에서 사진 리뷰는 일부라는 가정. 이미지는 만들지 않고 표시만 한다.
PHOTO_RATE = 0.3


def _pick(options: dict[str, float], rng: random.Random) -> str:
    return rng.choices(list(options), weights=list(options.values()))[0]


def pick_options(category: str, rng: random.Random) -> dict:
    """(option_size, option_color, has_photo) 를 정한다. 난수를 뽑는 순서(사이즈→색상→사진)는 고정이다."""
    sizes = SIZE_OPTIONS.get(category)
    size = _pick(sizes, rng) if sizes else DEFAULT_SIZE
    return {
        "option_size": size,
        "option_color": _pick(COLOR_OPTIONS, rng),
        "has_photo": rng.random() < PHOTO_RATE,
    }
