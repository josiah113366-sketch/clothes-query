import math

import pytest

from sim.behavior import params
from sim.behavior.ranking import ProductRanking
from sim.common.rng import SimRandom

SIZE = 1_000
DRAWS = 100_000


def _within_5_sigma(hits: int, n: int, p: float) -> bool:
    return abs(hits - n * p) <= 5 * math.sqrt(n * p * (1 - p))


@pytest.fixture(scope="module")
def ranks() -> list[int]:
    ranking = ProductRanking(SIZE, 7, params.PURCHASE_CURVE)
    rng = SimRandom(1)
    return [ranking.sample_rank(rng) for _ in range(DRAWS)]


@pytest.mark.parametrize(("top", "share"), [(0.01, 0.186), (0.05, 0.44), (0.20, 0.791)])
def test_purchase_concentration_follows_hm(ranks: list[int], top: float, share: float) -> None:
    hits = sum(1 for r in ranks if r < top * SIZE)
    assert _within_5_sigma(hits, DRAWS, share)


def test_rank_fraction_is_inverse_of_curve() -> None:
    ranking = ProductRanking(SIZE, 7, params.PURCHASE_CURVE)
    for x, y in params.PURCHASE_CURVE[:-1]:
        assert ranking.rank_fraction(y) == pytest.approx(x)
    assert ranking.rank_fraction(0.186 / 2) == pytest.approx(0.005)  # 구간 안은 선형


def test_same_seed_same_permutation() -> None:
    a = ProductRanking(SIZE, 7, params.PURCHASE_CURVE)
    b = ProductRanking(SIZE, 7, params.PURCHASE_CURVE)
    c = ProductRanking(SIZE, 8, params.PURCHASE_CURVE)
    assert a.order == b.order
    assert a.order != c.order
    assert sorted(a.order) == list(range(SIZE))


def test_sample_distinct() -> None:
    ranking = ProductRanking(20, 7, params.PURCHASE_CURVE)
    picked = ranking.sample_distinct(SimRandom(3), 15)
    assert len(set(picked)) == 15
    with pytest.raises(ValueError):
        ranking.sample_distinct(SimRandom(3), 21)


def test_bad_curve_and_empty_catalog_are_rejected() -> None:
    with pytest.raises(ValueError):
        ProductRanking(0, 7, params.PURCHASE_CURVE)
    with pytest.raises(ValueError):
        ProductRanking(10, 7, ((0.0, 0.0), (0.5, 0.5), (0.4, 0.9), (1.0, 1.0)))


def test_params_tables_sum_to_one() -> None:
    assert sum(p for p, _, _ in params.LINE_COUNT_BUCKETS) == pytest.approx(1)
    assert sum(w for _, w in params.QUANTITY_WEIGHTS) == pytest.approx(1)
    assert sum(w for _, w in params.METHOD_WEIGHTS) == pytest.approx(1)
    assert sum(w for _, w in params.CUSTOMER_FAILURE_CODES) == pytest.approx(1)
    assert sum(w for _, w in params.PG_FAILURE_CODES) == pytest.approx(1)
    # 재시도 실패 원인 비율은 첫 시도와 같은 고객 7 : PG 1
    assert params.RETRY_FAIL_CUSTOMER / params.RETRY_FAIL_PG == pytest.approx(7)
    assert params.RETRY_FAIL_CUSTOMER + params.RETRY_FAIL_PG == pytest.approx(0.3)
