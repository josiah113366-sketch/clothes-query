"""UTC/KST 날짜 경계와 동일 리뷰의 재전송 처리만 검증한다."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pipelines.silver.reviews import run


def _review(
    review_id: str,
    created_at: str,
    emitted_at: str = "2026-10-16T00:00:00+00:00",
    text: str = "지퍼가 걸립니다",
) -> dict[str, object]:
    return {
        "schema_version": "review.v2",
        "event_type": "review_created",
        "event_id": f"E-{review_id}",
        "review_id": review_id,
        "product_id": "P-1",
        "product_name": "가상 상품",
        "category": "여성의류",
        "order_id": "O-1",
        "created_at": created_at,
        "emitted_at": emitted_at,
        "rating": 2,
        "text": text,
        "source": "simulator",
        "member_id": "C-test-only",
    }


def _write_input(root: Path, utc_day: str, rows: list[dict[str, object]]) -> None:
    path = root / "reviews" / f"dt={utc_day}" / "part-00000.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def _output(root: Path, kst_day: str) -> list[dict[str, object]]:
    path = root / "silver" / "reviews" / f"dt={kst_day}" / "part-00000.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_kst_boundary_deduplication_and_repeat_run(tmp_path: Path) -> None:
    source, target = tmp_path / "bronze", tmp_path / "silver-output"
    original = _review("R-1", "2026-10-15T23:30:00+00:00")
    replay = dict(original, event_id="E-replay", emitted_at="2026-10-16T01:00:00+00:00")
    next_day = _review("R-2", "2026-10-16T15:30:00+00:00")
    _write_input(source, "2026-10-15", [original, replay])
    _write_input(source, "2026-10-16", [next_day])

    counts = run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16))
    first = _output(target, "2026-10-16")
    assert counts == {"2026-10-16": 1}
    assert first[0]["review_id"] == "R-1"
    assert first[0]["event_id"] == "E-replay"
    assert first[0]["created_at_kst"] == "2026-10-16T08:30:00+09:00"
    assert "member_id" not in first[0]

    run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16))
    assert _output(target, "2026-10-16") == first
