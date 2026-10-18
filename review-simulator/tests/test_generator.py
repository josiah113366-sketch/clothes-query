from rsim.review.generator import (
    JSON_INSTRUCTION,
    SYSTEM_TEMPLATE,
    build_user_prompt,
    generate_checked,
    normalize_jamo,
    parse_reviews,
)
from rsim.review.scenario import ReviewSpec

from .test_scenario import _specs


def test_prompt_has_no_evidence_rule() -> None:
    # p5.6: 근거 문구(evidence) 출력은 뺐다
    assert "evidence" not in SYSTEM_TEMPLATE
    assert "evidence" not in JSON_INSTRUCTION
    assert "활용성·사용감" in SYSTEM_TEMPLATE


def test_parse_reviews_handles_code_fence() -> None:
    text = '```json\n{"reviews": [{"spec_id": "s1", "text": "좋아요"}]}\n```'
    assert parse_reviews(text) == [{"spec_id": "s1", "text": "좋아요"}]
    assert parse_reviews("응답 없음") is None


def test_normalize_jamo() -> None:
    # 조합용 중성 ㅜ(U+116E) → 호환용 ㅜ(U+315C)
    assert normalize_jamo("좋아요ᅮᅮ") == "좋아요ㅜㅜ"


def test_user_prompt_lists_do_not_mention() -> None:
    spec = _specs(4, 1)[0]
    prompt = build_user_prompt([spec], [{"text": "예시", "rating": 5}], {spec.spec_id: "고칠 점"})
    assert "do_not_mention" in prompt and "fix_previous" in prompt


class _FakeGen:
    """검수 루프만 시험하는 가짜 생성기. 첫 시도는 일부러 속성을 빠뜨리고, 재시도에서는 고친다."""

    def __init__(self, specs: list[ReviewSpec], fix_on_retry: bool) -> None:
        self.by_id = {s.spec_id: s for s in specs}
        self.fix_on_retry = fix_on_retry
        self.calls = 0
        self.usage = {"verify_calls": 0, "verify_input_tokens": 0, "verify_output_tokens": 0}
        self.aspect_stats = {"checked": 0, "failed_first": 0, "dropped": 0}
        self.aspect_retries = 1
        self.verifier_call = self._verify

    def _generate_once(self, specs, feedback=None):
        self.calls += 1
        good = self.calls > 1 and self.fix_on_retry
        return {s.spec_id: {"text": "ok" if good else "bad"} for s in specs}

    def _verify(self, system, user, max_tokens):
        import json
        import re

        items = json.loads(user[user.index("[") : user.index("\n\n## 출력 형식")])
        labels = []
        for it in items:
            spec = self.by_id[it["id"]]
            aspects = spec.aspects if it["text"] == "ok" else []  # bad = 속성 누락
            labels.append({"id": it["id"], "aspects": [dict(a, phrase="x") for a in aspects]})
        assert re.search("라벨러", system)
        out = json.dumps({"labels": labels}, ensure_ascii=False)
        return 200, {"output": {"message": {"content": [{"text": out}]}}, "usage": {}}


def test_checked_loop_retries_then_keeps() -> None:
    specs = _specs(5, 3)
    gen = _FakeGen(specs, fix_on_retry=True)
    out = generate_checked(gen, specs)
    assert set(out) == {s.spec_id for s in specs}
    assert all(v["aspect_retry"] == 1 for v in out.values())


def test_checked_loop_drops_after_retry() -> None:
    specs = _specs(6, 3)
    gen = _FakeGen(specs, fix_on_retry=False)
    assert generate_checked(gen, specs) == {}
    assert gen.aspect_stats["dropped"] == 3
