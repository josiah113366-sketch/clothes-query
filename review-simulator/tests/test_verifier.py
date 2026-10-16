from types import SimpleNamespace

from rsim.review.verifier import blocking, compare, merge_truth, parse_labels, problems_to_feedback

SPEC = SimpleNamespace(
    aspects=[{"aspect": "배송", "sentiment": "긍정"}, {"aspect": "사이즈·핏", "sentiment": "부정"}]
)


def test_compare_finds_missing_extra_and_sentiment() -> None:
    labels = [
        {"aspect": "배송", "sentiment": "중립", "phrase": "보통"},
        {"aspect": "가격·가성비", "sentiment": "긍정", "phrase": "싸요"},
    ]
    problems = compare(SPEC, labels)
    assert "missing:사이즈·핏" in problems
    assert "extra:가격·가성비" in problems
    assert "sentiment:배송:긍정→중립" in problems


def test_extra_aspect_does_not_block_but_goes_to_truth() -> None:
    # p5.4 결정: 덧붙인 속성은 재생성 사유가 아니고 정답 라벨에 추가된다
    labels = [
        {"aspect": "배송", "sentiment": "긍정", "phrase": "빨라요"},
        {"aspect": "사이즈·핏", "sentiment": "부정", "phrase": "작아요"},
        {"aspect": "가격·가성비", "sentiment": "긍정", "phrase": "싸요"},
    ]
    assert blocking(compare(SPEC, labels)) == []
    truth = merge_truth(SPEC, labels)
    assert [a["source"] for a in truth] == ["spec", "spec", "verifier"]


def test_parse_labels_drops_unknown_values() -> None:
    text = (
        '```json\n{"labels": [{"id": "s1", "aspects": ['
        '{"aspect": "배송", "sentiment": "긍정"}, {"aspect": "모름", "sentiment": "긍정"}]}]}\n```'
    )
    assert parse_labels(text) == {"s1": [{"aspect": "배송", "sentiment": "긍정", "phrase": ""}]}
    assert parse_labels("not json") is None


def test_feedback_is_korean_sentence() -> None:
    assert "사이즈·핏" in problems_to_feedback(["missing:사이즈·핏"])
