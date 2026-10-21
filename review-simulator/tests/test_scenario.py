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


def test_style_rules_p58() -> None:
    # 재구매 말투 약 30%, 장단점 말투는 긍정·부정이 섞인 명세에만 (2026-10-16 lemin)
    from rsim.review.taxonomy import PROS_CONS_STYLE, REBUY_STYLE

    specs = _specs(4, 2000)
    rebuy = sum(s.style == REBUY_STYLE for s in specs) / len(specs)
    assert 0.26 < rebuy < 0.34
    for s in specs:
        if s.style == PROS_CONS_STYLE:
            assert {"긍정", "부정"} <= {a["sentiment"] for a in s.aspects}
    assert any(s.style == PROS_CONS_STYLE for s in specs)


def test_prompt_p58_priority_and_rebuy() -> None:
    from rsim.review.generator import PROMPT_VERSION, SYSTEM_TEMPLATE

    assert PROMPT_VERSION == "p5.8"
    assert "① 속성·감성 ② 길이 ③ 말투" in SYSTEM_TEMPLATE
    assert (
        "재구매" not in SYSTEM_TEMPLATE
    )  # 재구매 말투와 부딪히던 금지어 예시를 뺐다(규칙 부분만 확인)


def test_neutral_share_about_5_percent() -> None:
    # 2026-10-16 lemin 결정: 속성 감성 중 중립은 약 5% (scenario.SENTIMENT_BY_RATING)
    aspects = [a for s in _specs(5, 3000) for a in s.aspects]
    share = sum(a["sentiment"] == "중립" for a in aspects) / len(aspects)
    assert 0.03 <= share <= 0.08, share
