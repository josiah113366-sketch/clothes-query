from pathlib import Path

import pytest
from behavior_fixtures import StaticCatalog, StaticMembers, make_catalog, make_member_ids
from typer.testing import CliRunner

import sim.behavior.cli as behavior_cli
from sim.behavior.sink import MemoryOrderSink
from sim.cli import app

runner = CliRunner()
LOCAL = "postgresql://u:pw@localhost:5432/clothes"


def test_help_lists_options() -> None:
    result = runner.invoke(app, ["behavior", "live", "--help"])
    assert result.exit_code == 0
    for option in (
        "--mode",
        "--visits-daily",
        "--speed",
        "--duration",
        "--max-visits",
        "--control-file",
        "--seed",
        "--run-salt",
        "--click-sink",
        "--click-file",
    ):
        assert option in result.output


def test_refuses_remote_db_without_switch(monkeypatch) -> None:
    host, password = "prod-db.internal.example.net", "s3cr3t-pw"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{password}@{host}:5432/clothes")
    monkeypatch.delenv("SIM_ALLOW_REMOTE_DB", raising=False)
    result = runner.invoke(app, ["behavior", "live", "--max-visits", "1"])
    assert result.exit_code == 1
    assert "SIM_ALLOW_REMOTE_DB=1" in result.output
    assert host not in result.output and password not in result.output


@pytest.mark.parametrize("args", [["--mode", "surge"], ["--click-sink", "kafka"]])
def test_rejects_bad_choices(monkeypatch, args) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    result = runner.invoke(app, ["behavior", "live", *args])
    assert result.exit_code == 1


def test_run_prints_start_and_summary_without_pii(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setattr(behavior_cli, "DbOrderSink", lambda url: MemoryOrderSink())
    monkeypatch.setattr(
        behavior_cli, "DbMemberSource", lambda url: StaticMembers(make_member_ids(200))
    )
    monkeypatch.setattr(
        behavior_cli, "DbCatalogSource", lambda url: StaticCatalog(make_catalog(100))
    )
    click_file = tmp_path / "clicks.jsonl"
    result = runner.invoke(
        app,
        [
            "behavior",
            "live",
            "--mode",
            "burst",
            "--speed",
            "3600",
            "--max-visits",
            "30",
            "--run-salt",
            "7",
            "--click-sink",
            "jsonl",
            "--click-file",
            str(click_file),
            "--control-file",
            str(tmp_path / "none.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "대상 DB: localhost:5432/clothes" in out and "pw" not in out
    assert "run_salt: 7" in out and "회원: 200명  상품: 100개" in out
    assert "총 방문: 30건" in out
    assert "example.com" not in out and "010-" not in out
    assert click_file.exists()
