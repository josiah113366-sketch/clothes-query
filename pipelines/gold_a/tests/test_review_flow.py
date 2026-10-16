"""리뷰 원본에서 Silver, Gold A까지 같은 날짜로 연결되는지 확인한다."""

import json
from datetime import date
from pathlib import Path

from pipelines.gold_a.reviews import run_aggregate, search_reviews
from pipelines.silver.reviews import run


def test_review_flow_reprocesses_without_double_count(tmp_path: Path) -> None:
    source = tmp_path / "source"
    silver = tmp_path / "silver-output"
    gold = tmp_path / "gold-output"
    raw_file = source / "reviews" / "dt=2026-10-07" / "part-00000.jsonl"
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

    result_file = gold / "gold_a" / "review_product_daily" / "dt=2026-10-08" / "part-00000.jsonl"
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
    assert result_file.read_text(encoding="utf-8") == ""
