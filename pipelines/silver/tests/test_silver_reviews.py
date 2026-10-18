"""UTC/KST 날짜 경계와 동일 리뷰의 재전송 처리만 검증한다."""

from __future__ import annotations

import json
import importlib.util
from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from pipelines.silver.reviews import _input_uris, run
from pipelines.silver import reviews


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
    day = date.fromisoformat(utc_day)
    path = root / "reviews" / f"year={day:%Y}" / f"month={day:%m}" / f"day={day:%d}" / "part-00000.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def _output(root: Path, kst_day: str) -> list[dict[str, object]]:
    day = date.fromisoformat(kst_day)
    manifest = json.loads((root / "silver/reviews/scopes" / f"{kst_day}_{kst_day}" / "current.json").read_text(encoding="utf-8"))
    path = Path(manifest["outputs"][f"year={day:%Y}/month={day:%m}/day={day:%d}/part-00000.jsonl"])
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


def test_current_producer_path_duplicates_and_truth_separation(tmp_path: Path) -> None:
    # 최신 main의 실제 LakeSink로 파일을 만들어 생산자/소비자 경로를 함께 확인한다.
    sink_path = Path(__file__).resolve().parents[3] / "review-simulator/src/rsim/review/sinks.py"
    spec = importlib.util.spec_from_file_location("review_sink_compat", sink_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source, target = tmp_path / "bronze", tmp_path / "output"
    original = _review("R-1", "2026-10-15T23:30:00+00:00")
    newer = dict(original, emitted_at="2026-10-16T01:00:00+00:00", event_id="E-new")
    sink = module.LakeSink(str(source), str(source))
    sink.send(original, {"evaluation_only": True})
    sink.send(newer, None)
    sink.send(_review("R-2", "2026-10-16T03:00:00+00:00"), None)
    sink.close()
    assert (source / "reviews/year=2026/month=10/day=15/part-00000.jsonl").is_file()
    counts = run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16))
    rows = _output(target, "2026-10-16")
    assert counts == {"2026-10-16": 2}
    assert [row["review_id"] for row in rows] == ["R-1", "R-2"]
    assert rows[0]["event_id"] == "E-new"
    assert run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16)) == counts
    assert _output(target, "2026-10-16") == rows


def test_s3_lists_current_partition_without_network(monkeypatch) -> None:
    prefixes = []

    class Paginator:
        def paginate(self, Bucket, Prefix):
            prefixes.append(Prefix)
            return [{"Contents": [{"Key": Prefix + "part-00000.jsonl"}, {"Key": Prefix + "_SUCCESS"}]}]

    client = SimpleNamespace(get_paginator=lambda operation: Paginator())
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda service: client))
    paths = _input_uris("s3://test-bucket/bronze", date(2026, 10, 15))
    assert prefixes == ["bronze/reviews/year=2026/month=10/day=15/"]
    assert len(paths) == 1


def test_missing_input_preserves_output_but_explicit_empty_file_clears_day(tmp_path: Path) -> None:
    source, target = tmp_path / "bronze", tmp_path / "output"
    _write_input(source, "2026-10-15", [_review("R-1", "2026-10-15T23:30:00+00:00")])
    run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16))
    previous = _output(target, "2026-10-16")
    with pytest.raises(FileNotFoundError):
        run(str(tmp_path / "missing"), str(target), date(2026, 10, 16), date(2026, 10, 16))
    assert _output(target, "2026-10-16") == previous
    _write_input(source, "2026-10-15", [])
    assert run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16)) == {"2026-10-16": 0}


def test_review_errors_conflicts_and_incomplete_scope(tmp_path):
    source, target = tmp_path / "source", tmp_path / "output"
    bad = _review("bad", "2026-10-15T23:30:00Z")
    conflict = _review("conflict", "2026-10-15T23:30:00Z")
    good = _review("good", "2026-10-15T23:30:00Z")
    outside = _review("outside", "2026-10-15T00:30:00Z")
    _write_input(source, "2026-10-15", [bad, dict(bad, rating=7), conflict,
                 dict(conflict, text="different"), dict(conflict, emitted_at="2026-10-17T00:00:00Z"), good, dict(good), outside,
                 dict(_review("unknown-date", "invalid"))])
    counts = run(str(source), str(target), date(2026, 10, 16), date(2026, 10, 16))
    assert counts == {"2026-10-16": 1}
    assert _output(target, "2026-10-16")[0]["review_id"] == "good"
    pointer = target / "silver/reviews/scopes/2026-10-16_2026-10-16/current.json"
    manifest = json.loads(pointer.read_text(encoding="utf-8"))
    dq = json.loads(Path(manifest["outputs"]["dq_results.jsonl"]).read_text(encoding="utf-8"))
    assert manifest["status"] == "INCOMPLETE"
    assert dq["affected_scope"] == "REQUESTED_RANGE"
    assert dq["outside_range_count"] == 1
    assert dq["conflict_count"] == 2
    assert dq["input_count"] == dq["accepted_count"] + dq["duplicate_count"] + dq["quarantined_count"]
    issues = Path(manifest["outputs"]["quarantined_records.jsonl"]).read_text(encoding="utf-8")
    assert "source_line" in issues and '"text"' not in issues and "C-test-only" not in issues


def test_review_range_publish_failure_keeps_previous_bundle(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "output"
    _write_input(source, "2026-10-15", [_review("R-1", "2026-10-15T23:30:00Z")])
    _write_input(source, "2026-10-16", [_review("R-2", "2026-10-16T23:30:00Z")])
    start, end = date(2026, 10, 16), date(2026, 10, 17)
    run(str(source), str(target), start, end)
    pointer = target / "silver/reviews/scopes/2026-10-16_2026-10-17/current.json"
    previous = pointer.read_bytes()
    write = reviews._write_text
    def fail_second_day(uri, body):
        if "/day=17/" in uri.replace("\\", "/"):
            raise OSError("simulated storage failure")
        write(uri, body)
    monkeypatch.setattr(reviews, "_write_text", fail_second_day)
    with pytest.raises(OSError):
        run(str(source), str(target), start, end)
    assert pointer.read_bytes() == previous
    manifest = json.loads(previous)
    assert all(Path(path).exists() for path in manifest["outputs"].values())
