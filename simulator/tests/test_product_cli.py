import pytest
from product_fixtures import write_seed
from typer.testing import CliRunner

from sim.product import cli as product_cli

runner = CliRunner()


def test_dry_run_reports_files_and_never_connects(tmp_path, monkeypatch) -> None:
    write_seed(tmp_path)

    def must_not_connect(*args, **kwargs):
        raise AssertionError("--dry-run은 DB에 접속하면 안 됩니다")

    monkeypatch.setattr(product_cli, "connect", must_not_connect)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = runner.invoke(product_cli.app, ["load", "--dry-run", "--source", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "product_design: 30행" in result.output
    assert "product_variant: 90행" in result.output
    assert "모드: dry-run" in result.output
    assert "대상 DB" not in result.output


def test_load_without_yes_asks_and_stops_on_no(tmp_path, monkeypatch) -> None:
    write_seed(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:secret@localhost:5432/db")
    monkeypatch.setattr(product_cli, "connect", lambda *_: pytest.fail("거절했는데 접속함"))
    result = runner.invoke(product_cli.app, ["load", "--source", str(tmp_path)], input="n\n")
    assert result.exit_code == 1
    assert "localhost:5432/db" in result.output
    assert "secret" not in result.output


def test_missing_source_is_a_clear_error(tmp_path) -> None:
    result = runner.invoke(product_cli.app, ["load", "--dry-run", "--source", str(tmp_path)])
    assert result.exit_code == 1
    assert "파일이 없습니다" in result.output
