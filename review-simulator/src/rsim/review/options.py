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

# category 가 없는 상품(실제 상품 데이터, 2026-10-16)은 상품 종류(product_type) 이름으로 사이즈 묶음을 고른다.
# 아래 단어가 들어 있으면 그 묶음, 아무것도 없으면 의류 사이즈("clothing"). 대소문자는 무시한다.
SIZE_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "shoes": (
        "신발",
        "운동화",
        "구두",
        "샌들",
        "부츠",
        "슬리퍼",
        "로퍼",
        "shoe",
        "sneaker",
        "boot",
        "sandal",
        "slipper",
        "pump",
        "flat",
    ),
    "free": (
        "가방",
        "모자",
        "벨트",
        "스카프",
        "목도리",
        "장갑",
        "양말",
        "지갑",
        "액세서리",
        "bag",
        "hat",
        "cap",
        "beanie",
        "belt",
        "scarf",
        "glove",
        "sock",
        "wallet",
        "accessor",
        "earring",
        "necklace",
        "sunglass",
        "umbrella",
    ),
}
# 묶음별 사이즈 분포. 의류는 여성·남성 사이즈를 합친 분포다.
SIZE_GROUPS: dict[str, dict[str, float]] = {
    "clothing": {"XS": 0.06, "S": 0.2, "M": 0.32, "L": 0.25, "XL": 0.12, "XXL": 0.05},
    "shoes": SIZE_OPTIONS["패션슈즈"],
    "free": SIZE_OPTIONS["잡화"],
}


def size_group_of(product_type: str | None) -> str:
    """상품 종류 이름 → 사이즈 묶음 ("clothing" / "shoes" / "free")."""
    name = (product_type or "").lower()
    for group, words in SIZE_GROUP_KEYWORDS.items():
        if any(w in name for w in words):
            return group
    return "clothing"


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

# 상품 정보의 색상(catalog.Product.info["color"])이 영어로 올 때(H&M colour_group_name) 옵션 이름으로 바꾸는 표.
# 대소문자는 무시한다. 표에 없는 색은 받은 이름 그대로 쓴다. 자주 나오는 색만 넣었다.
COLOR_ALIASES: dict[str, str] = {
    "black": "블랙",
    "white": "화이트",
    "off white": "아이보리",
    "grey": "그레이",
    "gray": "그레이",
    "dark grey": "그레이",
    "light grey": "그레이",
    "dark blue": "네이비",
    "navy": "네이비",
    "blue": "블루",
    "light blue": "블루",
    "beige": "베이지",
    "light beige": "베이지",
    "dark beige": "베이지",
    "brown": "브라운",
    "khaki": "카키",
    "khaki green": "카키",
    "dark green": "카키",
    "red": "레드",
    "dark red": "레드",
    "pink": "핑크",
    "light pink": "핑크",
    "yellow": "옐로우",
    "green": "그린",
    "orange": "오렌지",
    "purple": "퍼플",
}


def option_color_of(color: str) -> str:
    """상품 색상 → 리뷰의 option_color 값 (영어면 COLOR_ALIASES 로 바꾸고, 없으면 그대로)."""
    return COLOR_ALIASES.get(color.strip().lower(), color.strip())


# 포토 리뷰 비율 (0~1). 국내 패션몰에서 사진 리뷰는 일부라는 가정. 이미지는 만들지 않고 표시만 한다.
PHOTO_RATE = 0.3


def _pick(options: dict[str, float], rng: random.Random) -> str:
    return rng.choices(list(options), weights=list(options.values()))[0]


def pick_options(
    category: str | None,
    rng: random.Random,
    color: str | None = None,
    product_type: str | None = None,
) -> dict:
    """(option_size, option_color, has_photo) 를 정한다. 난수를 뽑는 순서(사이즈→색상→사진)는 고정이다.

    color: 상품 정보에 색상이 있으면 그 색을 option_color 로 쓴다(2026-10-16).
           그래도 색상 난수는 똑같이 한 번 뽑고 버린다. 그래야 has_photo 같은 뒤의 값이
           상품 정보가 있든 없든 같은 난수에서 나온다(같은 주문이면 포토 여부가 바뀌지 않음).
    product_type: category 가 없을 때 사이즈 묶음을 고르는 데 쓴다(size_group_of).
    """
    if category is None:
        sizes = SIZE_GROUPS[size_group_of(product_type)]
    else:
        sizes = SIZE_OPTIONS.get(category)
    size = _pick(sizes, rng) if sizes else DEFAULT_SIZE
    drawn = _pick(COLOR_OPTIONS, rng)
    return {
        "option_size": size,
        "option_color": option_color_of(color) if color else drawn,
        "has_photo": rng.random() < PHOTO_RATE,
    }
