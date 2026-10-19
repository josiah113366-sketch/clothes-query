"""리뷰 원본에서 Silver, Gold A까지 같은 날짜로 연결되는지 확인한다."""

import json
import pytest
from datetime import date
from pathlib import Path

from pipelines.gold_a.reviews import run_aggregate, search_reviews
from pipelines.silver.reviews import run


def test_review_flow_reprocesses_without_double_count(tmp_path: Path) -> None:
    source = tmp_path / "source"
    silver = tmp_path / "silver-output"
    gold = tmp_path / "gold-output"
    raw_file = source / "reviews/year=2026/month=10/day=07/part-00000.jsonl"
    raw_file.parent.mkdir(parents=True)
    raw = {
        "schema_version": "review.v2", "event_type": "review_created",
        "event_id": "E-1", "review_id": "R-1", "product_id": "P-1",
        "created_at": "2026-10-07T23:30:00+00:00",
        "emitted_at": "2026-10-08T00:00:00+00:00",
        "rating": 2, "text": "지퍼가 걸려요", "member_id": "dummy-member",
    }
    raw_file.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")
    day = date(2026, 10, 8)

    for _ in range(2):
        assert run(str(source), str(silver), day, day) == {"2026-10-08": 1}
        assert run_aggregate(str(silver), str(gold), day, day) == {"2026-10-08": 1}

    pointer = gold / "gold_a/review_product_daily/scopes/2026-10-08_2026-10-08/current.json"
    manifest = json.loads(pointer.read_text(encoding="utf-8"))
    result_file = Path(manifest["outputs"]["year=2026/month=10/day=08/part-00000.jsonl"])
    assert manifest["inputs"]["silver_reviews"]["check_version"] == "reviews.v1"
    result = [json.loads(line) for line in result_file.read_text(encoding="utf-8").splitlines()]
    assert result == [{
        "review_date_kst": "2026-10-08", "product_id": "P-1",
        "review_count": 1, "average_rating": 2.0, "low_rating_count": 1,
    }]
    total, matches = search_reviews(str(silver), day, day, "지퍼", "P-1")
    assert total == 1
    assert matches[0]["review_id"] == "R-1"
    assert "member_id" not in matches[0]

    raw_file.write_text("", encoding="utf-8")
    assert run(str(source), str(silver), day, day) == {"2026-10-08": 0}
    assert run_aggregate(str(silver), str(gold), day, day) == {"2026-10-08": 0}
    manifest = json.loads(pointer.read_text(encoding="utf-8"))
    assert Path(manifest["outputs"]["year=2026/month=10/day=08/part-00000.jsonl"]).read_text(encoding="utf-8") == ""


def test_incomplete_or_missing_review_input_preserves_gold(tmp_path):
    source, silver, gold = (tmp_path / name for name in ("source", "silver", "gold"))
    raw_file = source / "reviews/year=2026/month=10/day=07/part-00000.jsonl"
    raw_file.parent.mkdir(parents=True)
    raw = {"schema_version": "review.v2", "event_type": "review_created", "event_id": "E-1",
           "review_id": "R-1", "product_id": "P-1", "created_at": "2026-10-07T23:30:00Z",
           "emitted_at": "2026-10-08T00:00:00Z", "rating": 2, "text": "test review"}
    raw_file.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    day = date(2026, 10, 8)
    run(str(source), str(silver), day, day)
    run_aggregate(str(silver), str(gold), day, day)
    pointer = gold / "gold_a/review_product_daily/scopes/2026-10-08_2026-10-08/current.json"
    previous = pointer.read_bytes()
    raw_file.write_text(json.dumps(dict(raw, rating=7)) + "\n", encoding="utf-8")
    run(str(source), str(silver), day, day)
    with pytest.raises(ValueError, match="PASS"):
        run_aggregate(str(silver), str(gold), day, day)
    with pytest.raises(ValueError):
        search_reviews(str(silver), day, day, "test")
    assert pointer.read_bytes() == previous
    # manifest만 PASS로 잘못 표시해도 실제 품질 결과에서 다시 중단한다.
    silver_pointer = silver / "silver/reviews/scopes/2026-10-08_2026-10-08/current.json"
    manifest = json.loads(silver_pointer.read_text(encoding="utf-8"))
    manifest["status"] = "PASS"
    silver_pointer.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="품질"):
        run_aggregate(str(silver), str(gold), day, day)
    assert pointer.read_bytes() == previous
    silver_pointer.unlink()
    with pytest.raises(FileNotFoundError):
        run_aggregate(str(silver), str(gold), day, day)
    assert pointer.read_bytes() == previous
