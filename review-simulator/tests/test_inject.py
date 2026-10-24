"""rsim inject (직접 작성한 리뷰 넣기) 테스트. LLM·실제 AWS 는 부르지 않는다."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rsim.cli import app

runner = CliRunner()
DAY = Path(".local/lake/reviews/year=2026/month=10/day=08")
TRUTH_DAY = Path(".local/lake/reviews_truth/year=2026/month=10/day=08")
HEADER = "text,rating,product_id,created_at,aspects,product_name,category,has_photo\n"


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_inject_csv_to_lake_next_to_daily_file(workdir) -> None:
    # 매일 도는 파일(part-00000)이 이미 있는 날짜 파티션에 넣어도 그 파일은 그대로 남아야 한다
    daily = workdir / DAY / "part-00000.jsonl"
    daily.parent.mkdir(parents=True)
    daily.write_text('{"review_id": "R-daily"}\n', encoding="utf-8")

    src = _write(
        workdir / ".local/manual/size_spike.csv",
        '"너무 작아요",2,X-1,2026-10-08,사이즈·핏:부정|배송:긍정,테스트 니트,여성의류,true\n'
        '"라벨 없는 문장",4,X-1,2026-10-08T20:00:00+09:00,,테스트 니트,여성의류,\n',
    )
    res = runner.invoke(app, ["inject", "--file", str(src)])
    assert res.exit_code == 0, res.output

    assert _rows(daily) == [{"review_id": "R-daily"}]
    out = _rows(workdir / DAY / "part-manual-size_spike.jsonl")
    assert len(out) == 2
    first = out[0]
    assert first["review_id"].startswith("M-") and first["source"] == "manual"
    assert first["schema_version"] == "review.v2" and first["has_photo"] is True
    # 날짜만 적으면 KST 정오 → UTC 같은 날짜 파티션
    assert first["created_at"] == "2026-10-08T12:00:00+09:00"
    assert first["option_size"] and first["option_color"] and first["member_id"]

    # 정답은 라벨을 적은 줄만
    truth = _rows(workdir / TRUTH_DAY / "part-manual-size_spike.jsonl")
    assert [t["review_id"] for t in truth] == [first["review_id"]]
    assert truth[0]["aspects"] == [
        {"aspect": "사이즈·핏", "sentiment": "부정"},
        {"aspect": "배송", "sentiment": "긍정"},
    ]

    # 같은 파일을 다시 넣으면 덮어써서 같은 ID 로 2건만 남는다
    runner.invoke(app, ["inject", "--file", str(src)])
    again = _rows(workdir / DAY / "part-manual-size_spike.jsonl")
    assert [r["review_id"] for r in again] == [r["review_id"] for r in out]


def test_inject_rejects_bad_rows_and_writes_nothing(workdir) -> None:
    src = _write(
        workdir / ".local/manual/bad.csv",
        '"좋아요",9,X-1,2026-10-08,,테스트 니트,여성의류,\n'
        '"상품 정보 없음",3,X-2,2026-10-08,,,,\n'
        '"속성 오타",3,X-1,2026-10-08,사이즈:부정,테스트 니트,여성의류,\n'
        '"정상",3,X-1,2026-10-08,,테스트 니트,여성의류,\n',
    )
    res = runner.invoke(app, ["inject", "--file", str(src)])
    assert res.exit_code != 0
    assert "1번째" in res.output and "2번째" in res.output and "3번째" in res.output
    assert "4번째" not in res.output
    assert not (workdir / ".local/lake").exists()


def test_inject_dry_run_and_private_guard(workdir) -> None:
    src = _write(workdir / ".local/manual/ok.csv", '"좋아요",5,X-1,,,테스트 니트,여성의류,\n')
    res = runner.invoke(app, ["inject", "--file", str(src), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert not (workdir / ".local/lake").exists()

    private = _write(workdir / "private/real.csv", '"원문",5,X-1,,,테스트 니트,여성의류,\n')
    res = runner.invoke(app, ["inject", "--file", str(private)])
    assert res.exit_code != 0 and "private" in res.output


def test_inject_reads_and_writes_s3(workdir, monkeypatch) -> None:
    # ECS 에서 쓰는 방식: 입력도 S3, 결과도 S3 (moto 가짜 S3)
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setenv("LAKE_ROOT", "s3://test-lake/bronze_v2")
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="ap-northeast-1")
        s3.create_bucket(
            Bucket="test-lake",
            CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
        )
        body = HEADER + '"작아요",2,X-1,2026-10-08,사이즈·핏:부정,테스트 니트,여성의류,\n'
        s3.put_object(Bucket="test-lake", Key="sim-input/manual/t1.csv", Body=body.encode())
        res = runner.invoke(app, ["inject", "--file", "s3://test-lake/sim-input/manual/t1.csv"])
        assert res.exit_code == 0, res.output
        keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket="test-lake")["Contents"])
        assert "bronze_v2/reviews/year=2026/month=10/day=08/part-manual-t1.jsonl" in keys
