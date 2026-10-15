from rsim.review.taxonomy import AIHUB_ASPECT_MAP, ASPECT_WEIGHTS, ASPECTS


def test_eleven_aspects_same_as_label_guide_v3() -> None:
    # 라벨 가이드 v3: 10개 + 활용성·사용감
    assert len(ASPECTS) == 11
    assert "활용성·사용감" in ASPECTS


def test_every_aspect_has_weight() -> None:
    assert set(ASPECT_WEIGHTS) == set(ASPECTS)
    assert all(w > 0 for w in ASPECT_WEIGHTS.values())


def test_aihub_map_targets_known_aspects() -> None:
    assert set(AIHUB_ASPECT_MAP.values()) <= set(ASPECTS)
    # v3: 신축성은 재질·촉감, 보온성은 활용성·사용감
    assert AIHUB_ASPECT_MAP["신축성"] == "재질·촉감"
    assert AIHUB_ASPECT_MAP["보온성"] == "활용성·사용감"
