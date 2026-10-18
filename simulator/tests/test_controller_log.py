import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from sim.behavior import params as behavior_params
from sim.common.control import ControlState, FileControlSource
from sim.controller import model
from sim.controller.control_writer import FileControlWriter
from sim.controller.log import (
    S3_PREFIX,
    FileIncidentLog,
    IncidentLogError,
    S3IncidentLog,
    record_filename,
)

RECORD = {
    "schema_version": 1,
    "incident_id": "11111111-2222-3333-4444-555555555555",
    "phase": "start",
    "type": "PG_OUTAGE",
    "at": "2026-10-18T08:12:00Z",
    "params": {"pg": "PG_B", "extra_fail": 0.85, "planned_minutes": 10},
}


def test_pg_names_match_behavior() -> None:
    assert model.PGS == behavior_params.PGS


def test_utc_text_and_stamp() -> None:
    kst = timezone(timedelta(hours=9))
    at = datetime(2026, 10, 18, 17, 12, 0, tzinfo=kst)
    assert model.utc_text(at) == "2026-10-18T08:12:00Z"
    assert model.file_stamp(at) == "20261018T081200Z"
    with pytest.raises(ValueError):
        model.utc_text(datetime(2026, 10, 18))


def test_file_log_writes_one_file_per_record(tmp_path: Path) -> None:
    log = FileIncidentLog(tmp_path / "incident_log")
    log.write(RECORD)
    files = list((tmp_path / "incident_log").iterdir())
    assert [f.name for f in files] == [
        "20261018T081200Z_11111111-2222-3333-4444-555555555555_start.json"
    ]
    assert json.loads(files[0].read_text(encoding="utf-8")) == RECORD
    with pytest.raises(IncidentLogError):  # 같은 파일을 덮어쓰지 않는다
        log.write(RECORD)
    assert len(list((tmp_path / "incident_log").iterdir())) == 1


def test_file_log_failure_is_incident_log_error(tmp_path: Path) -> None:
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    with pytest.raises(IncidentLogError):
        FileIncidentLog(blocker / "sub").write(RECORD)


class FakeS3:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def put_object(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail


def test_s3_log_puts_under_prefix() -> None:
    client = FakeS3()
    S3IncidentLog("secret-bucket-name", client=client).write(RECORD)
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Key"] == S3_PREFIX + record_filename(RECORD)
    assert call["Key"].startswith("ground_truth/incident_log/20261018T081200Z_")
    assert json.loads(call["Body"]) == RECORD


def test_s3_log_failure_hides_bucket_and_key() -> None:
    from botocore.exceptions import ClientError, EndpointConnectionError

    denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "secret-bucket-name denied"}}, "PutObject"
    )
    with pytest.raises(IncidentLogError) as info:
        S3IncidentLog("secret-bucket-name", client=FakeS3(denied)).write(RECORD)
    with pytest.raises(IncidentLogError):
        offline = EndpointConnectionError(endpoint_url="https://secret-bucket-name.s3")
        S3IncidentLog("secret-bucket-name", client=FakeS3(offline)).write(RECORD)
    message = str(info.value)
    assert "AccessDenied" in message
    assert "secret-bucket-name" not in message and "ground_truth" not in message


def test_control_writer_is_atomic_and_readable(tmp_path: Path) -> None:
    path = tmp_path / ".local" / "control.json"
    writer = FileControlWriter(path)
    writer.write(True, "burst", {"PG_B": 0.85})
    assert json.loads(path.read_text()) == {
        "running": True,
        "mode": "burst",
        "pg_extra_fail": {"PG_B": 0.85},
    }
    assert FileControlSource(path).read() == ControlState(True, "burst", {"PG_B": 0.85})
    writer.write(False, "normal", {})
    assert writer.read_current() == ControlState(False, "normal", {})
    assert [p.name for p in path.parent.iterdir()] == ["control.json"]  # 임시 파일이 남지 않는다
    with pytest.raises(ValueError):
        writer.write(True, "surge", {})


def test_control_writer_uses_replace(tmp_path: Path, monkeypatch) -> None:
    calls = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (calls.append((a, b)), real(a, b)))
    FileControlWriter(tmp_path / "control.json").write(True, "normal", {})
    assert len(calls) == 1 and Path(calls[0][1]).name == "control.json"


def test_ended_by_values() -> None:
    assert set(model.ENDED_BY) == {"timer", "manual", "shutdown", "complete", "failed"}
    assert model.MODE_INCIDENTS == {"medium": "TRAFFIC_SURGE", "burst": "INGEST_LAG"}
    _ = UTC
