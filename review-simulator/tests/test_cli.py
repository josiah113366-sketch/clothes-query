import json

from typer.testing import CliRunner

import rsim
from rsim.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert rsim.__version__ in result.stdout


def test_run_fake_to_jsonl(workdir) -> None:
    # Bedrock 없이 가짜 문장으로 5건 → 파일. 리뷰와 정답 파일이 같은 review_id 로 이어져야 한다.
    result = runner.invoke(app, ["run", "--llm", "fake", "--sink", "jsonl", "--count", "5"])
    assert result.exit_code == 0, result.output
    out = workdir / ".local" / "out"
    reviews = [json.loads(x) for x in (out / "reviews.jsonl").read_text("utf-8").splitlines()]
    truths = [json.loads(x) for x in (out / "reviews_truth.jsonl").read_text("utf-8").splitlines()]
    assert len(reviews) == len(truths) == 5
    assert [r["review_id"] for r in reviews] == [t["review_id"] for t in truths]
    assert "aspects" not in reviews[0]  # 리뷰 토픽에는 정답 라벨이 없다


def test_run_fake_is_reproducible_with_seed(workdir) -> None:
    args = ["run", "--llm", "fake", "--sink", "jsonl", "--count", "3", "--out"]
    runner.invoke(app, [*args, ".local/a.jsonl", "--start", "2026-10-01T00:00:00+09:00"])
    runner.invoke(app, [*args, ".local/b.jsonl", "--start", "2026-10-01T00:00:00+09:00"])
    a = (workdir / ".local" / "a.jsonl").read_text("utf-8")
    b = (workdir / ".local" / "b.jsonl").read_text("utf-8")
    assert a == b  # 같은 RANDOM_SEED + 같은 시작 시각이면 ID·명세·문장까지 같다


def test_run_bedrock_without_key_stops(workdir) -> None:
    result = runner.invoke(app, ["run", "--count", "1"])
    assert result.exit_code != 0


def test_bench_without_yes_makes_no_call(workdir) -> None:
    result = runner.invoke(app, ["bench", "--n", "5"])
    assert result.exit_code == 0, result.output
    assert "호출 안 함" in result.stdout
