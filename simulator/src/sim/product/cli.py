from typing import Annotated

import typer

from sim.common.config import ConfigError, load_config
from sim.common.db import SafeDatabaseError, connect, describe_target
from sim.product import params
from sim.product.load import TableMissingError, TableNotEmptyError, run_load
from sim.product.source import SourceError
from sim.product.verify import run_verify

app = typer.Typer(help="상품 시드(Parquet)를 DB에 옮기고 확인", no_args_is_help=True)

SOURCE_HELP = "원본 디렉터리 또는 s3://버킷/seed_v2 (기본: SEED_DIR, 없으면 .local/seed_v2)"
CHECK_COUNT = 8


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


@app.command()
def load(
    source: Annotated[str | None, typer.Option(help=SOURCE_HELP)] = None,
    batch_size: Annotated[
        int,
        typer.Option(min=params.MIN_BATCH_SIZE, max=params.MAX_BATCH_SIZE, help="COPY 배치 크기"),
    ] = params.DEFAULT_BATCH_SIZE,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="DB에 접속하지 않고 파일 스키마와 행 수만 본다")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="확인 질문을 건너뛴다")] = False,
) -> None:
    """상품 Parquet 2개를 product_design, product_variant에 한 트랜잭션으로 적재한다."""
    try:
        config = load_config(require_database=not dry_run)
    except ConfigError as error:
        raise _fail(str(error)) from None
    source = source or config.seed_dir

    def progress(table: str, done: int, total: int) -> None:
        typer.echo(f"{table}: {done:,} / {total:,}")

    try:
        if dry_run:
            summary = run_load(source, batch_size)
        else:
            typer.echo(f"대상 DB: {describe_target(config.database_url)}")
            if not yes and not typer.confirm("계속할까요?", default=False):
                raise typer.Exit(1)
            with connect(config.database_url) as conn:
                summary = run_load(source, batch_size, conn, progress)
    except (SourceError, SafeDatabaseError, TableNotEmptyError, TableMissingError) as error:
        raise _fail(str(error)) from None

    typer.echo("")
    for line in summary.lines():
        typer.echo(line)


@app.command()
def verify(
    source: Annotated[str | None, typer.Option(help=SOURCE_HELP)] = None,
) -> None:
    """원본 Parquet와 DB를 비교해 8개 항목을 확인한다 (읽기 전용)."""
    try:
        config = load_config()
    except ConfigError as error:
        raise _fail(str(error)) from None
    try:
        with connect(config.database_url) as conn:
            results = run_verify(conn, source or config.seed_dir)
    except (SourceError, SafeDatabaseError) as error:
        raise _fail(str(error)) from None

    typer.echo("| # | 확인 | 결과 | 상세 |")
    typer.echo("|---|---|---|---|")
    for r in results:
        typer.echo(f"| {r.number} | {r.name} | {'통과' if r.passed else '실패'} | {r.detail} |")
    failed = [r for r in results if not r.passed]
    typer.echo(f"\n{len(results) - len(failed)}/{CHECK_COUNT} 통과")
    if failed:
        raise typer.Exit(1)
