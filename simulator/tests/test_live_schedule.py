import math
from datetime import datetime, timedelta

import pytest

from sim.common import curve
from sim.common.rng import SimRandom
from sim.member import params
from sim.member.schedule import next_interval, signups_per_second

MONDAY = datetime(2026, 10, 12, 0, 0, 0, tzinfo=params.KST)  # 월요일 00:00 KST
DAILY = params.NORMAL_DAILY_SIGNUPS


def _arrivals(rng: SimRandom, seconds: float, daily: float, mode: str) -> list[datetime]:
    """MONDAY부터 seconds 동안의 가입 시각. 간격은 뽑는 시점의 시각으로 뽑는다."""
    elapsed, times = 0.0, []
    while True:
        elapsed += next_interval(rng, daily, mode, MONDAY + timedelta(seconds=elapsed))
        if elapsed >= seconds:
            return times
        times.append(MONDAY + timedelta(seconds=elapsed))


def _within_5_sigma(count: int, expected: float) -> bool:
    return abs(count - expected) <= 5 * math.sqrt(expected)


def test_rate_formula() -> None:
    monday_20 = MONDAY.replace(hour=20)
    assert signups_per_second(86_400, "normal", monday_20) == pytest.approx(0.896 * 1.8)
    assert signups_per_second(86_400, "medium", MONDAY) == pytest.approx(5.4)
    assert signups_per_second(5000, "burst", MONDAY) == pytest.approx(5000 * 18 / 86_400)


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        next_interval(SimRandom(1), DAILY, "surge", MONDAY)


def test_normal_fourteen_days_within_5_sigma() -> None:
    count = len(_arrivals(SimRandom(1), 14 * params.SECONDS_PER_DAY, DAILY, "normal"))
    assert _within_5_sigma(count, 14 * DAILY)


@pytest.mark.parametrize(("mode", "factor"), [("burst", 18.0), ("medium", 5.4)])
def test_fixed_mode_one_hour_within_5_sigma(mode: str, factor: float) -> None:
    count = len(_arrivals(SimRandom(2), 3_600, DAILY, mode))
    assert _within_5_sigma(count, DAILY * factor / 24)


def test_normal_week_follows_hour_shares() -> None:
    times = _arrivals(SimRandom(3), 7 * params.SECONDS_PER_DAY, DAILY, "normal")
    total = len(times)
    for start, end, share in curve.HOUR_SHARE:
        count = sum(1 for t in times if start <= t.hour < end)
        sigma = math.sqrt(total * share * (1 - share))
        assert abs(count - total * share) <= 5 * sigma, (start, end)


def test_same_seed_same_intervals() -> None:
    a, b = SimRandom(5), SimRandom(5)
    args = (1500, "normal", MONDAY)
    assert [next_interval(a, *args) for _ in range(20)] == [
        next_interval(b, *args) for _ in range(20)
    ]
