"""회원 현재 상태에서 중복·변경 순서·재처리 위험만 확인한다."""

import json
from datetime import date
from pathlib import Path

import pytest

from pipelines.silver.members import run


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
    run(str(tmp_path / "bronze" / "members-events"), str(output), date(2026, 10, 15))
    assert Path(path).read_bytes() == first

    conflicting = {**changed, "marketing_consent": True}
    update_file.write_text(
        "".join(json.dumps(row) + "\n" for row in (changed, conflicting)),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="동일 원천 시각"):
        run(str(tmp_path / "bronze" / "members-events"), str(output), date(2026, 10, 15))
