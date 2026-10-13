import typer

from sim import __version__

app = typer.Typer(help="clothes-query 시뮬레이터")


@app.callback()
def main() -> None:
    """clothes-query 시뮬레이터."""


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(__version__)
