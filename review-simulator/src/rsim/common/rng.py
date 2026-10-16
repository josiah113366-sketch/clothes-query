"""시드 고정 난수 도구.

리뷰 시뮬레이터는 전역 random, uuid.uuid4() 를 직접 쓰지 않고 여기서 만든 random.Random 하나만 쓴다.
같은 시드면 같은 명세(상품·별점·속성·감성)와 같은 ID 가 같은 순서로 나온다. (LLM 이 쓰는 문장은 매번 다를 수 있다)
simulator/ 의 sim.common.rng 와 같은 방식(derive_seed)을 쓰지만, 모듈끼리 import 하지 않도록 따로 둔다.
"""

from __future__ import annotations

import hashlib
import random
import secrets
import uuid


def derive_seed(seed: int, *names: object) -> int:
    """시드와 이름들로 다른 줄기의 시드를 만든다 (SHA-256 기반, 같은 입력이면 항상 같은 값).

    예: derive_seed(42, "seeds") 는 시드 표본 추출용, derive_seed(42, "scenario") 는 명세용처럼
    용도별로 난수열을 나누면, 한쪽에서 난수를 더 뽑아도 다른 쪽 결과가 바뀌지 않는다.
    """
    material = "\x1f".join([str(seed), *(str(name) for name in names)]).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def resolve_seed(seed: int | None) -> int:
    """시드가 없으면(RANDOM_SEED 비움) 새로 하나 만든다. 만든 값은 로그에 남겨서 같은 실행을 재현할 수 있게 한다."""
    return seed if seed is not None else secrets.randbits(32)


def make_rng(seed: int) -> random.Random:
    """시드 고정 난수 생성기."""
    return random.Random(seed)


def seeded_uuid(rng: random.Random) -> uuid.UUID:
    """난수 생성기로 만든 UUID(버전 4 형식). uuid.uuid4() 대신 써서 같은 시드면 같은 ID 가 나오게 한다."""
    return uuid.UUID(int=rng.getrandbits(128), version=4)
