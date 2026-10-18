"""상품 인기 순위. 시드로 섞은 순열 + 구간 선형 누적표의 역함수 추첨.

나중에 실제 가중치 파일로 바꿀 수 있도록 바깥에는 sample(rng) -> 상품 인덱스만 보인다.
"""

import random
from collections.abc import Sequence
from itertools import pairwise

from sim.common.rng import SimRandom


class ProductRanking:
    def __init__(
        self, size: int, permutation_seed: int, curve: Sequence[tuple[float, float]]
    ) -> None:
        if size <= 0:
            raise ValueError("상품이 없습니다.")
        _check_curve(curve)
        order = list(range(size))
        random.Random(permutation_seed).shuffle(order)
        self.size = size
        self.order: tuple[int, ...] = tuple(order)  # 순위 r(0이 1위) → 상품 인덱스
        self._curve = tuple(curve)

    def rank_fraction(self, u: float) -> float:
        """누적 비율 u ∈ [0, 1)을 순위 비율로 바꾼다 (구간 안에서는 균등)."""
        for (x0, y0), (x1, y1) in pairwise(self._curve):
            if u < y1:
                return x0 + (u - y0) / (y1 - y0) * (x1 - x0)
        return self._curve[-1][0]

    def sample_rank(self, rng: SimRandom) -> int:
        rank = int(self.rank_fraction(rng.random.random()) * self.size)
        return min(rank, self.size - 1)

    def sample(self, rng: SimRandom) -> int:
        """상품 인덱스 하나."""
        return self.order[self.sample_rank(rng)]

    def sample_distinct(self, rng: SimRandom, count: int) -> list[int]:
        """서로 다른 상품 인덱스 count개 (뽑은 순서대로)."""
        if count > self.size:
            raise ValueError("상품 수보다 많이 뽑을 수 없습니다.")
        picked: list[int] = []
        seen: set[int] = set()
        while len(picked) < count:
            index = self.sample(rng)
            if index not in seen:
                seen.add(index)
                picked.append(index)
        return picked


def _check_curve(curve: Sequence[tuple[float, float]]) -> None:
    if curve[0] != (0.0, 0.0) or curve[-1] != (1.0, 1.0):
        raise ValueError("누적표는 (0, 0)에서 시작해 (1, 1)에서 끝나야 합니다.")
    for (x0, y0), (x1, y1) in pairwise(curve):
        if not (x1 > x0 and y1 > y0):
            raise ValueError("누적표는 두 값 모두 늘어나야 합니다.")
