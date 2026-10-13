from pathlib import Path
from typing import Annotated

import typer

from sim.common.config import ConfigError, load_config
from sim.common.db import SafeDatabaseError, connect, describe_target
from sim.common.regions import RegionFileError, load_regions
from sim.member import params
from sim.member.baseline import TableNotEmptyError, run_baseline, write_summary
from sim.member.verify import run_verify

app = typer.Typer(help="회원 생성과 적재", no_args_is_help=True)

SUMMARY_PATH = Path(".local/baseline_run.json")


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


@app.command()
def baseline(
    count: Annotated[int, typer.Option(min=1, max=params.PHONE_SPACE, help="만들 회원 수")] = (
        params.DEFAULT_COUNT
    ),
    seed: Annotated[int | None, typer.Option(help="난수 시드 (기본: SIM_SEED, 없으면 42)")] = None,
    batch_size: Annotated[
        int,
        typer.Option(min=params.MIN_BATCH_SIZE, max=params.MAX_BATCH_SIZE, help="COPY 배치 크기"),
    ] = params.DEFAULT_BATCH_SIZE,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="DB에 쓰지 않고 생성만 한다")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="확인 질문을 건너뛴다")] = False,
) -> None:
    """회원을 만들어 member 테이블에 한 번에 적재한다."""
    try:
        config = load_config(require_database=not dry_run)
        regions = load_regions(config.region_file)
    except (ConfigError, RegionFileError) as error:
        raise _fail(str(error)) from None
    seed = config.seed if seed is None else seed

    def progress(done: int, total: int) -> None:
        typer.echo(f"{done:,} / {total:,}")

    if dry_run:
        summary = run_baseline(regions, count, seed, batch_size, None, progress)
    else:
        typer.echo(f"대상 DB: {describe_target(config.database_url)}")
        if not yes and not typer.confirm("계속할까요?", default=False):
            raise typer.Exit(1)
        try:
            conn = connect(config.database_url)
            with conn:
                summary = run_baseline(regions, count, seed, batch_size, conn, progress)
        except (SafeDatabaseError, TableNotEmptyError) as error:
            raise _fail(str(error)) from None
        write_summary(summary, SUMMARY_PATH)

    typer.echo("")
    for line in summary.lines():
        typer.echo(line)
    if not dry_run:
        typer.echo(f"요약 파일: {SUMMARY_PATH}")


@app.command()
def verify(
    expected: Annotated[int, typer.Option(help="기대하는 행 수")] = params.DEFAULT_COUNT,
) -> None:
    """적재 결과를 확인한다 (읽기 전용, 집계만 본다)."""
    try:
        config = load_config()
        regions = load_regions(config.region_file)
    except (ConfigError, RegionFileError) as error:
        raise _fail(str(error)) from None
    try:
        with connect(config.database_url) as conn:
            results = run_verify(conn, regions, expected)
    except SafeDatabaseError as error:
        raise _fail(str(error)) from None

    typer.echo("| # | 확인 | 결과 | 상세 |")
    typer.echo("|---|---|---|---|")
    for r in results:
        typer.echo(f"| {r.number} | {r.name} | {'통과' if r.passed else '실패'} | {r.detail} |")
    failed = [r for r in results if not r.passed]
    typer.echo(f"\n{len(results) - len(failed)}/12 통과" if len(results) == 12 else "\n확인 중단")
    if failed or len(results) < 12:
        raise typer.Exit(1)
