import typer

from sim import __version__
from sim.cdc.cli import app as cdc_app
from sim.member.cli import app as member_app
from sim.product.cli import app as product_app
from sim.sink.cli import app as sink_app

app = typer.Typer(help="clothes-query 시뮬레이터")
app.add_typer(member_app, name="member")
app.add_typer(cdc_app, name="cdc")
app.add_typer(sink_app, name="sink")
app.add_typer(product_app, name="product")


@app.callback()
def main() -> None:
    """clothes-query 시뮬레이터."""


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(__version__)
