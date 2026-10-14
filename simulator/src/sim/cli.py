import typer

from sim import __version__
from sim.cdc.cli import app as cdc_app
from sim.member.cli import app as member_app

app = typer.Typer(help="clothes-query 시뮬레이터")
app.add_typer(member_app, name="member")
app.add_typer(cdc_app, name="cdc")


@app.callback()
def main() -> None:
    """clothes-query 시뮬레이터."""


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(__version__)
