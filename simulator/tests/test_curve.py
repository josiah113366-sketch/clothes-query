from datetime import UTC, datetime, timedelta

import pytest

from sim.common import curve
from sim.common.timezone import KST

MONDAY = datetime(2026, 10, 12, 0, 0, 0, tzinfo=KST)  # 월요일 00:00 KST


def test_tables_are_valid() -> None:
    curve.validate()
    assert sum(curve.WEEKDAY_RATIO) == pytest.approx(1, abs=1e-9)
    assert sum(share for _, _, share in curve.HOUR_SHARE) == pytest.approx(1, abs=1e-9)
    hours = [h for start, end, _ in curve.HOUR_SHARE for h in range(start, end)]
    assert hours == list(range(24))  # 빈틈·겹침 없이 0~24시


def test_peak_hour_factor_is_computed_from_table() -> None:
    assert curve.PEAK_HOUR_FACTOR == pytest.approx(1.8)


def test_weekly_average_of_normal_is_one() -> None:
    week = 7 * 86_400
    total = sum(curve.rate_factor("normal", MONDAY + timedelta(seconds=s)) for s in range(week))
    assert total / week == pytest.approx(1.0, abs=1e-6)


def test_factor_values() -> None:
    monday_20 = MONDAY.replace(hour=20)
    assert curve.weekday_factor(monday_20) == pytest.approx(0.896)
    assert curve.hour_factor(monday_20) == pytest.approx(1.8)
    assert curve.hour_factor(MONDAY.replace(hour=3)) == pytest.approx(0.20)
    assert curve.hour_factor(MONDAY.replace(hour=13)) == pytest.approx(1.32)
    saturday = MONDAY + timedelta(days=5)
    assert curve.weekday_factor(saturday) == pytest.approx(1.113)


@pytest.mark.parametrize("hours", [0, 3, 13, 20, 24 * 5 + 23])
def test_medium_and_burst_are_fixed(hours: int) -> None:
    t = MONDAY + timedelta(hours=hours)
    assert curve.rate_factor("medium", t) == pytest.approx(5.4)
    assert curve.rate_factor("burst", t) == pytest.approx(18.0)


def test_day_boundary_is_kst_midnight() -> None:
    sunday_last = MONDAY - timedelta(seconds=1)  # 일요일 23:59:59 KST
    assert curve.weekday_factor(sunday_last) == pytest.approx(7 * 0.127)
    assert curve.weekday_factor(MONDAY) == pytest.approx(7 * 0.128)
    # UTC 일요일 15:00 = KST 월요일 00:00
    utc = datetime(2026, 10, 11, 15, 0, 0, tzinfo=UTC)
    assert curve.weekday_factor(utc) == pytest.approx(7 * 0.128)
    assert curve.hour_factor(utc) == pytest.approx(0.20)


def test_naive_datetime_is_rejected() -> None:
    naive = datetime(2026, 10, 12, 20, 0, 0)
    for mode in ("normal", "medium", "burst"):
        with pytest.raises(ValueError):
            curve.rate_factor(mode, naive)


@pytest.mark.parametrize("mode", ["surge", "", "Burst"])
def test_unknown_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValueError):
        curve.rate_factor(mode, MONDAY)


def test_validate_rejects_bad_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curve, "WEEKDAY_RATIO", (0.2,) * 7)
    with pytest.raises(ValueError):
        curve.validate()
    monkeypatch.undo()
    monkeypatch.setattr(curve, "HOUR_SHARE", ((0, 12, 0.5), (13, 24, 0.5)))
    with pytest.raises(ValueError):
        curve.validate()
