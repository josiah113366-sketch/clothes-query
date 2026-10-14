from pathlib import Path

from typer.testing import CliRunner

from sim.cli import app

runner = CliRunner()


def test_live_help_lists_options() -> None:
    result = runner.invoke(app, ["member", "live", "--help"])
    assert result.exit_code == 0
    for option in (
        "--mode",
        "--daily",
        "--surge-multiplier",
        "--speed",
        "--duration",
        "--max-signups",
        "--control-file",
        "--seed",
    ):
        assert option in result.output


def test_live_refuses_non_local_database(monkeypatch, tmp_path: Path) -> None:
    secret_host = "prod-db.internal.example.net"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:pw@{secret_host}:5432/clothes")
    result = runner.invoke(app, ["member", "live", "--max-signups", "1"])
    assert result.exit_code == 1
    assert "로컬" in result.output
    assert secret_host not in result.output  # 접속 정보는 오류에도 싣지 않는다


def test_live_rejects_unknown_mode(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@localhost:5432/clothes")
    result = runner.invoke(app, ["member", "live", "--mode", "turbo"])
    assert result.exit_code == 1
