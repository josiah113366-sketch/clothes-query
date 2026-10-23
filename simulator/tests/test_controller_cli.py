import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from sim.cli import app
from sim.controller.control_writer import MemoryControlWriter
from sim.controller.log import MemoryIncidentLog
from sim.controller.pollution import MemoryPollution
from sim.controller.server import ControllerServer
from sim.controller.service import ControllerService

runner = CliRunner()
TOKEN = "cli-token-xyz"


def test_help_lists_commands_and_serve_options() -> None:
    result = runner.invoke(app, ["controller", "--help"])
    assert result.exit_code == 0
    for command in (
        "serve",
        "status",
        "mode",
        "running",
        "pg-outage",
        "pollution",
        "sink-pause",
        "end",
    ):
        assert command in result.output
    result = runner.invoke(app, ["controller", "serve", "--help"])
    for option in (
        "--host",
        "--port",
        "--control-file",
        "--incident-log",
        "--incident-dir",
        "--medium-minutes",
        "--burst-minutes",
    ):
        assert option in result.output


def test_client_without_server_fails_clearly() -> None:
    result = runner.invoke(app, ["controller", "status", "--url", "http://127.0.0.1:9"])
    assert result.exit_code == 1
    assert "연결하지 못했습니다" in result.output


def test_serve_refuses_non_local_without_token(monkeypatch) -> None:
    monkeypatch.delenv("SIM_CONTROLLER_TOKEN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:secretpw@localhost:5432/clothes")
    result = runner.invoke(app, ["controller", "serve", "--host", "0.0.0.0", "--port", "0"])
    assert result.exit_code == 1
    assert "SIM_CONTROLLER_TOKEN" in result.output and "secretpw" not in result.output


def test_serve_s3_requires_bucket(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "")
    result = runner.invoke(app, ["controller", "serve", "--incident-log", "s3", "--port", "0"])
    assert result.exit_code == 1 and "S3_BUCKET" in result.output


def test_client_commands_talk_to_server(monkeypatch) -> None:
    service = ControllerService(
        MemoryControlWriter(),
        MemoryIncidentLog(),
        MemoryPollution(),
        lambda: datetime(2026, 10, 18, tzinfo=UTC),
        iter(f"id-{i}" for i in range(100)).__next__,
    )
    server = ControllerServer(service, "127.0.0.1", 0, TOKEN)
    server.start()
    url = f"http://127.0.0.1:{server.port}"
    try:
        monkeypatch.delenv("SIM_CONTROLLER_TOKEN", raising=False)
        result = runner.invoke(app, ["controller", "status", "--url", url])
        assert result.exit_code == 1 and "401" in result.output
        monkeypatch.setenv("SIM_CONTROLLER_TOKEN", TOKEN)
        result = runner.invoke(app, ["controller", "mode", "burst", "--url", url])
        assert result.exit_code == 0 and json.loads(result.output)["mode"] == "burst"
        result = runner.invoke(app, ["controller", "pg-outage", "--pg", "PG_B", "--url", url])
        assert result.exit_code == 1 and "409" in result.output
        assert runner.invoke(app, ["controller", "mode", "normal", "--url", url]).exit_code == 0
        result = runner.invoke(app, ["controller", "pollution", "--count", "5", "--url", url])
        assert result.exit_code == 0
        assert runner.invoke(app, ["controller", "running", "false", "--url", url]).exit_code == 0
        assert runner.invoke(app, ["controller", "running", "maybe", "--url", url]).exit_code == 1
        result = runner.invoke(app, ["controller", "end", "--url", url])
        assert result.exit_code == 1 and "400" in result.output  # 진행 중 사건 없음
        result = runner.invoke(app, ["controller", "sink-pause", "--url", url])
        assert result.exit_code == 0 and json.loads(result.output)["active"]["type"] == "SINK_PAUSE"
        assert runner.invoke(app, ["controller", "end", "--url", url]).exit_code == 0
        assert TOKEN not in result.output
    finally:
        server.stop()
