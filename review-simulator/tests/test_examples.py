"""예시 세트(data/examples/ex-vN.md)와 점검표 테스트 (2026-10-16 지시서 2단계). LLM 은 부르지 않는다."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rsim.bench.bench import make_specs
from rsim.bench.scorecard import scorecard_row
from rsim.cli import app
from rsim.common.config import load_settings
from rsim.common.rng import make_rng
from rsim.review.examples import load_example_set, parse_example_set
from rsim.review.generator import ConverseGenerator, build_system_prompt
from rsim.review.seeds import SeedPool

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "examples"
runner = CliRunner()


def test_ex_v0_matches_p58_examples() -> None:
    ex = load_example_set(EXAMPLES_DIR, "ex-v0")
    assert ex.seed_sources is None  # 예전처럼 모든 출처
    assert ex.lines.splitlines()[0].startswith('- 중립: 색상·디자인 "색은 무난해요"')
    prompt = build_system_prompt(ex.lines)
    assert ex.lines in prompt and "{examples}" not in prompt
    assert "{spec_id, text}" in prompt  # 출력 형식 줄의 중괄호는 그대로


def test_unfilled_template_is_refused() -> None:
    # 빈칸(____)이 코드블록 안에 남은 예시는 읽지 않는다 (덜 쓴 예시로 Bedrock 비용이 나가지 않게)
    body = '안내: ____ 를 채운다\n```text\n- 중립: 배송 "____"\n```\n'
    with pytest.raises(SystemExit, match="채우지 않은 칸"):
        parse_example_set("ex-t", body)
    # 코드블록 밖 안내 글의 ____ 는 상관없다
    assert parse_example_set("ex-t", body.replace('"____"', '"보통이에요"')).lines


def test_default_example_set_is_ex_v1(workdir) -> None:
    # 2026-10-18 lemin 결정: 기본 예시 세트 ex-v1 (lemin 이 채운 파일이 그대로 읽혀야 한다)
    settings = load_settings()
    assert settings.examples_version == "ex-v1"
    ex = load_example_set(settings.examples_dir, settings.examples_version)
    assert ex.seed_sources == ("aihub", "handwritten")


def test_parse_seed_sources_and_errors() -> None:
    body = 'seed_sources: aihub, handwritten\n\n```text\n- 중립: 배송 "보통이에요"\n```\n'
    ex = parse_example_set("ex-t", body)
    assert ex.seed_sources == ("aihub", "handwritten")
    assert ex.lines == '- 중립: 배송 "보통이에요"'
    with pytest.raises(SystemExit, match="쓸 수 없습니다"):
        parse_example_set("ex-t", body.replace("handwritten", "gemini"))
    with pytest.raises(SystemExit, match="코드블록이 없습니다"):
        parse_example_set("ex-t", "seed_sources: aihub\n")
    with pytest.raises(SystemExit, match="예시 파일이 없습니다"):
        load_example_set(EXAMPLES_DIR, "ex-v99")


def test_seed_sources_filter_keeps_specs(workdir) -> None:
    settings = load_settings()
    specs_all, _ = make_specs(settings, 6, 42)
    specs_cut, ex_cut = make_specs(settings, 6, 42, ("aihub", "handwritten"))
    # 말투 예시 출처를 줄여도 명세는 그대로 (예시 버전끼리 같은 명세로 비교)
    assert [(s.spec_id, s.aspects, s.style) for s in specs_all] == [
        (s.spec_id, s.aspects, s.style) for s in specs_cut
    ]
    assert all(e["source"] != "synth" for e in ex_cut)
    pool = SeedPool.load(settings.seeds_path, make_rng(0))
    assert pool.only(None) is pool
    assert {r["source"] for r in pool.only(("aihub",)).rows} == {"aihub"}


def test_generator_uses_example_set(workdir, monkeypatch) -> None:
    (workdir / "ex").mkdir()
    (workdir / "ex" / "ex-t.md").write_text(
        'seed_sources: aihub\n```text\n- 중립: 포장 "그냥 기본이에요"\n```\n', encoding="utf-8"
    )
    monkeypatch.setenv("EXAMPLES_DIR", str(workdir / "ex"))
    monkeypatch.setenv("EXAMPLES_VERSION", "ex-t")
    settings = load_settings()
    gen = ConverseGenerator(settings, SeedPool.load(settings.seeds_path, make_rng(0)))
    assert gen.examples_version == "ex-t"
    assert '포장 "그냥 기본이에요"' in gen.system_prompt
    assert {r["source"] for r in gen.seeds.rows} == {"aihub"}


def test_scorecard_row_and_command(workdir) -> None:
    summary = {
        "prompt_version": "p5.8",
        "examples_version": "ex-v1",
        "n_specs": 20,
        "models": {
            "m": {
                "aspect_pass_first": "13/20",
                "aspect_dropped": 3,
                "aspect_problem_counts_first": {"sentiment": 3, "extra": 10},
                "neutral_errors_first": 2,
                "problem_counts": {"too_many_sentences": 9, "length_out_of_range": 7},
                "input_tokens": 24291,
                "output_tokens": 6249,
                "cost_per_1000_reviews_usd": 0.286,
                "latency_sec_mean": 6.01,
            }
        },
    }
    row = scorecard_row("r1", summary, "m")
    assert row == (
        "| r1 | ex-v1 | p5.8 | 20 | 65% | 15% | 3/2 | 10 | 9/7 | 1215 | 312 | 0.286 | 6.01 |"
    )
    run_dir = workdir / ".local" / "bench" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    res = runner.invoke(app, ["scorecard"])
    assert res.exit_code == 0 and row in res.output
