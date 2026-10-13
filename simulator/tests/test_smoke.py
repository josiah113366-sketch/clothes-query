from typer.testing import CliRunner

import sim
from sim.cli import app


def test_package_importable() -> None:
    assert sim.__version__


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert sim.__version__ in result.stdout
