from rsim.common.rng import make_rng, seeded_uuid
from rsim.review.catalog import Catalog
from rsim.review.scenario import MAX_ASPECTS_SHORT, ScenarioEngine, SimClock
from rsim.review.taxonomy import ASPECTS, SENTIMENTS


def _specs(seed: int, n: int = 200) -> list:
    rng = make_rng(seed)
    names = {"여성의류": ["니트"], "남성의류": ["셔츠"], "패션슈즈": ["운동화"], "잡화": ["가방"]}
    catalog = Catalog.build(__import__("pathlib").Path("없는파일.csv"), names, rng)
    engine = ScenarioEngine(catalog, [], SimClock(None, 60, rng), rng, id_rng=make_rng(seed + 1))
    return [engine.next_spec() for _ in range(n)]


def _key(s) -> tuple:
    return (
        s.product.product_id,
        s.rating,
        str(s.aspects),
        s.style,
        s.length,
        s.age_group,
        s.member_id,
    )


def test_same_seed_same_specs() -> None:
    assert [_key(s) for s in _specs(1)] == [_key(s) for s in _specs(1)]
    assert [_key(s) for s in _specs(1)] != [_key(s) for s in _specs(2)]


def test_spec_values_are_valid() -> None:
    for s in _specs(3):
        assert 1 <= s.rating <= 5
        assert 1 <= len(s.aspects) <= 3
        assert len({a["aspect"] for a in s.aspects}) == len(s.aspects)  # 같은 속성 중복 없음
        assert all(a["aspect"] in ASPECTS and a["sentiment"] in SENTIMENTS for a in s.aspects)
        if s.length == "short":
            assert len(s.aspects) <= MAX_ASPECTS_SHORT


def test_seeded_uuid_is_reproducible() -> None:
    assert seeded_uuid(make_rng(5)) == seeded_uuid(make_rng(5))
    assert seeded_uuid(make_rng(5)).version == 4
