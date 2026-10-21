import math

from behavior_fixtures import make_member_ids

from sim.behavior import params, pool
from sim.behavior.pool import MemberPool, is_top_member
from sim.common.rng import SimRandom

PII_COLUMNS = ("name", "email", "phone", "birth_date", "password_hash")


def test_top_members_get_about_60_percent_of_visits(member_ids: list[str]) -> None:
    members = MemberPool(42, member_ids)
    rng = SimRandom(1)
    draws = 100_000
    top = {m for m in member_ids if is_top_member(42, m)}
    hits = sum(1 for _ in range(draws) if members.sample(rng) in top)
    share_top = len(top) / len(member_ids)
    p = share_top * 6 / (share_top * 6 + (1 - share_top))  # 상위 비율이 정확히 20%면 0.6
    assert abs(len(top) / len(member_ids) - params.TOP_MEMBER_SHARE) < 0.05
    assert abs(hits - draws * p) <= 5 * math.sqrt(draws * p * (1 - p))
    assert 0.55 < hits / draws < 0.65


def test_weight_is_stable_across_refresh(member_ids: list[str]) -> None:
    members = MemberPool(42, member_ids[:1_000])
    before = {m: pool.member_weight(42, m) for m in member_ids[:1_000]}
    members.update(member_ids)  # 새 회원이 들어와도
    assert all(pool.member_weight(42, m) == w for m, w in before.items())
    assert len(members) == len(member_ids)


def test_same_seed_same_draws(member_ids: list[str]) -> None:
    a, b = MemberPool(42, member_ids), MemberPool(42, list(reversed(member_ids)))
    ra, rb = SimRandom(9), SimRandom(9)
    assert [a.sample(ra) for _ in range(50)] == [b.sample(rb) for _ in range(50)]


def test_empty_pool_is_an_error() -> None:
    try:
        MemberPool(42, [])
    except ValueError as error:
        assert "sim member baseline" in str(error)
    else:
        raise AssertionError("빈 풀은 오류여야 한다")


def test_select_reads_no_pii_columns() -> None:
    for query in (pool.MEMBER_SQL, pool.CATALOG_SQL):
        lowered = query.lower()
        assert not any(column in lowered for column in PII_COLUMNS)
    assert pool.MEMBER_SQL.startswith("SELECT member_id FROM members")


def test_fixture_ids_are_sorted() -> None:
    ids = make_member_ids(10)
    assert ids == sorted(ids)
