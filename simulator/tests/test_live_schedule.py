import math
from datetime import datetime

import pytest

from sim.common.rng import SimRandom
from sim.member import params
from sim.member.schedule import mode_multiplier, next_interval, rate_multiplier, signups_per_second

T0 = datetime(2026, 10, 1, tzinfo=params.KST)


def _count_in(rng: SimRandom, days: float, daily: float, mode: str) -> int:
    horizon = days * params.SECONDS_PER_DAY
    elapsed, count = 0.0, 0
    while True:
        elapsed += next_interval(rng, daily, mode, params.SURGE_MULTIPLIER, T0)
        if elapsed >= horizon:
            return count
        count += 1


def test_rate_multiplier_is_flat_for_now() -> None:
    assert rate_multiplier(T0) == 1.0
    assert rate_multiplier(datetime(2026, 12, 25, 3, 0, tzinfo=params.KST)) == 1.0


def test_mode_multiplier() -> None:
    assert mode_multiplier("normal", 4.6) == 1.0
    assert mode_multiplier("surge", 4.6) == 4.6
    with pytest.raises(ValueError):
        mode_multiplier("turbo", 4.6)


def test_rate_formula() -> None:
    assert signups_per_second(86_400, "normal", 4.6, T0) == pytest.approx(1.0)
    assert signups_per_second(1500, "surge", 4.6, T0) == pytest.approx(1500 * 4.6 / 86_400)


def test_normal_ten_days_within_5_sigma() -> None:
    expected = 15_000
    count = _count_in(SimRandom(1), 10, params.NORMAL_DAILY_SIGNUPS, "normal")
    assert abs(count - expected) <= 5 * math.sqrt(expected)


def test_surge_one_day_within_5_sigma() -> None:
    expected = params.NORMAL_DAILY_SIGNUPS * params.SURGE_MULTIPLIER
    count = _count_in(SimRandom(2), 1, params.NORMAL_DAILY_SIGNUPS, "surge")
    assert abs(count - expected) <= 5 * math.sqrt(expected)


def test_same_seed_same_intervals() -> None:
    a, b = SimRandom(5), SimRandom(5)
    args = (1500, "normal", 4.6, T0)
    assert [next_interval(a, *args) for _ in range(20)] == [
        next_interval(b, *args) for _ in range(20)
    ]
