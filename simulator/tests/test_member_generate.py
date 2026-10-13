import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import sqrt

import pytest

from sim.common.rng import SimRandom
from sim.member import params
from sim.member.baseline import iter_members, run_baseline
from sim.member.generate import age_band_of, allocate_phones, generate_member, random_signup_at


def make(count: int, seed: int, regions):
    return list(iter_members(SimRandom(seed), count, regions))


def test_one_member_satisfies_ddl_rules(regions) -> None:
    rng = SimRandom(1)
    phone = allocate_phones(rng, 1)[0]
    for _ in range(300):
        m = generate_member(rng, random_signup_at(rng), regions, phone)
        assert m.gender in ("F", "M") and m.signup_channel in ("web", "app")
        assert m.status == "ACTIVE" and m.withdrawn_at is None
        assert m.signup_at.tzinfo is not None
        age = m.signup_at.astimezone(params.KST).year - m.birth_date.year
        assert age >= 16 and age_band_of(age) == m.age_band
        assert re.fullmatch(r"010-\d{4}-\d{4}", m.phone)
        assert re.fullmatch(r"user_[0-9a-f]{32}@example\.com", m.email)
        assert m.email == f"user_{m.member_id.replace('-', '')}@example.com"
        assert re.fullmatch(r"\$2b\$12\$[./A-Za-z0-9]{53}", m.password_hash)
        assert m.region_sigungu in regions.names


def test_naive_signup_at_rejected(regions) -> None:
    with pytest.raises(ValueError):
        generate_member(SimRandom(1), datetime(2026, 8, 1), regions, "010-0000-0000")


def test_seed_reproducible(regions) -> None:
    assert make(200, 5, regions) == make(200, 5, regions)
    assert make(200, 5, regions) != make(200, 6, regions)


def test_hash_independent_of_batch_size(regions) -> None:
    a = run_baseline(regions, 3000, 42, 1000)
    b = run_baseline(regions, 3000, 42, 5000)
    assert a.repro_hash == b.repro_hash
    assert run_baseline(regions, 3000, 43, 1000).repro_hash != a.repro_hash


def test_unique_values_at_20k(regions) -> None:
    members = make(20_000, 3, regions)
    for attr in ("member_id", "email", "phone"):
        assert len({getattr(m, attr) for m in members}) == 20_000


def test_distribution_at_50k(regions) -> None:
    n = 50_000
    members = make(n, 42, regions)
    bands = Counter(m.age_band for m in members)
    total_w = sum(params.AGE_BAND_WEIGHTS.values())
    for band, w in params.AGE_BAND_WEIGHTS.items():
        p = w / total_w
        assert abs(bands[band] / n - p) <= 5 * sqrt(p * (1 - p) / n)
    female = sum(m.gender == "F" for m in members)
    assert abs(female / n - 0.55) <= 5 * sqrt(0.55 * 0.45 / n)


def test_signup_within_period(regions) -> None:
    for m in make(5000, 9, regions):
        assert params.SIGNUP_START <= m.signup_at < params.SIGNUP_END
    assert params.SIGNUP_END - params.SIGNUP_START == timedelta(days=61)


def test_repr_hides_pii(regions) -> None:
    m = make(1, 1, regions)[0]
    text = repr(m)
    assert m.member_id in text
    for secret in (m.name, m.email, m.phone, m.password_hash, m.birth_date.isoformat()):
        assert secret not in text


def test_age_band_of_edges() -> None:
    assert [age_band_of(a) for a in (16, 19, 20, 69, 70, 99)] == [
        "~19",
        "~19",
        "20s",
        "60s",
        "70+",
        "70+",
    ]
    with pytest.raises(ValueError):
        age_band_of(15)


def test_offset_is_kst() -> None:
    assert params.KST == timezone(timedelta(hours=9))
