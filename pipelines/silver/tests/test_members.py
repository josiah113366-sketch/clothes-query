"""회원 현재 상태에서 중복·변경 순서·재처리 위험만 확인한다."""

import json
from datetime import date
from pathlib import Path

import pytest

from pipelines.silver.members import run
from pipelines.silver import members


def test_snapshot_update_and_reprocess(tmp_path: Path) -> None:
    source = tmp_path / "bronze" / "members-events" / "year=2026" / "month=10" / "day=14"
    source.mkdir(parents=True)
    base = {
        "member_id": "test-member",
        "age_band": "30s",
        "gender": "F",
        "signup_channel": "app",
        "region_sigungu": "test-region",
        "marketing_consent": False,
        "status": "ACTIVE",
        "signup_at": "2026-10-14T00:00:00+00:00",
        "created_at": "2026-10-14T00:00:00+00:00",
        "withdrawn_at": None,
        "__op": "r",
        "__source_ts_ms": 100,
        "__source_snapshot": "true",
    }
    changed = {
        **base,
        "status": "WITHDRAWN",
        "withdrawn_at": "2026-10-15T00:00:00+00:00",
        "__op": "u",
        "__source_ts_ms": 200,
        "__source_snapshot": None,
    }
    snapshot_file = source / "members-events+0+0000000000.json"
    snapshot_file.write_text(
        "".join(json.dumps(row) + "\n" for row in (base, base)), encoding="utf-8"
    )
    next_day = source.parent / "day=15"
    next_day.mkdir()
    update_file = next_day / "members-events+0+0000000001.json"
    update_file.write_text(json.dumps(changed) + "\n", encoding="utf-8")
    output = tmp_path / "output"
    count, files, path = run(str(tmp_path / "bronze" / "members-events"), str(output), date(2026, 10, 14))
    assert (count, files) == (1, 1)
    assert json.loads(Path(path).read_text(encoding="utf-8"))["status"] == "ACTIVE"
    count, files, path = run(str(tmp_path / "bronze" / "members-events"), str(output), date(2026, 10, 15))
    assert (count, files) == (1, 2)
    first = Path(path).read_bytes()
    row = json.loads(first)
    assert row["status"] == "WITHDRAWN"
    assert "name" not in row
    _, _, repeated = run(str(tmp_path / "bronze" / "members-events"), str(output), date(2026, 10, 15))
    assert Path(repeated).read_bytes() == first

    conflicting = {**changed, "marketing_consent": True}
    update_file.write_text(
        "".join(json.dumps(row) + "\n" for row in (changed, conflicting, dict(changed, __source_ts_ms=300))),
        encoding="utf-8",
    )
    count, _, path = run(str(tmp_path / "bronze" / "members-events"), str(output), date(2026, 10, 15))
    assert count == 0
    manifest = json.loads((output / "silver/members_current/as_of=2026-10-15/current.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "INCOMPLETE"
    issues = [json.loads(line) for line in Path(manifest["outputs"]["quarantined_records.jsonl"]).read_text(encoding="utf-8").splitlines()]
    assert any(row["error_code"] == "CONTENT_CONFLICT" for row in issues)



def test_invalid_member_blocks_stale_state_and_publish_failure_preserves_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source/year=2026/month=10/day=14"
    source.mkdir(parents=True)
    raw = {"member_id": "member-bad", "age_band": "30s", "gender": "F", "signup_channel": "app",
           "region_sigungu": "test-region", "marketing_consent": False, "status": "ACTIVE",
           "signup_at": "2026-10-14T00:00:00Z", "created_at": "2026-10-14T00:00:00Z",
           "withdrawn_at": None, "__op": "r", "__source_ts_ms": 100}
    rows = [raw, dict(raw), dict(raw, __op="u", __source_ts_ms=200, status="WITHDRAWN"),
            dict(raw, member_id="member-good"), dict(raw, member_id="member-good")]
    (source / "members-events+0+0000000000.json").write_text(
        "".join(json.dumps(row) + "\n" for row in rows) + "broken json\n", encoding="utf-8")
    output = tmp_path / "output"
    count, _, path = run(str(tmp_path / "source"), str(output), date(2026, 10, 14))
    assert count == 1
    assert json.loads(Path(path).read_text(encoding="utf-8"))["member_id"] == "member-good"
    pointer = output / "silver/members_current/as_of=2026-10-14/current.json"
    previous = pointer.read_bytes()
    manifest = json.loads(previous)
    dq = json.loads(Path(manifest["outputs"]["dq_results.jsonl"]).read_text(encoding="utf-8"))
    assert dq["input_count"] == dq["accepted_count"] + dq["duplicate_count"] + dq["quarantined_count"]
    assert dq["duplicate_count"] == 1
    assert dq["unknown_key_error_count"] == 1
    assert dq["affected_record_keys"] == ["member-bad"]
    write = members._write_text
    def fail_quality(uri, body):
        if uri.endswith("dq_results.jsonl"):
            raise OSError("simulated storage failure")
        write(uri, body)
    monkeypatch.setattr(members, "_write_text", fail_quality)
    with pytest.raises(OSError):
        run(str(tmp_path / "source"), str(output), date(2026, 10, 14))
    assert pointer.read_bytes() == previous
