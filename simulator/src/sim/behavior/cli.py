import os
from pathlib import Path
from typing import Annotated

import typer

from sim.behavior import params
from sim.behavior.pool import DbCatalogSource, DbMemberSource
from sim.behavior.runner import BehaviorError, BehaviorRunner, stop_on_signals
from sim.behavior.sink import ClickSink, DbOrderSink, JsonlClickSink, NullClickSink
from sim.common.clock import SimClock
from sim.common.config import ConfigError, load_config
from sim.common.control import DEFAULT_CONTROL_FILE, MODES, FileControlSource
from sim.common.db import DatabaseTargetError, SafeDatabaseError, check_db_target, describe_target

app = typer.Typer(help="쇼핑 행동: 방문, 주문, 결제, 상태 전이", no_args_is_help=True)

CLICK_SINKS = ("none", "jsonl")
ALLOW_REMOTE_ENV = "SIM_ALLOW_REMOTE_DB"


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


@app.command()
def live(
    mode: Annotated[
        str, typer.Option(envvar="SIM_LIVE_MODE", help=f"시작 모드 ({' | '.join(MODES)})")
    ] = "normal",
    visits_daily: Annotated[
        float, typer.Option(min=1, envvar="SIM_VISITS_DAILY", help="normal의 하루 평균 방문 수")
    ] = params.NORMAL_DAILY_VISITS,
    speed: Annotated[
        float, typer.Option(min=0.001, envvar="SIM_LIVE_SPEED", help="시간 배속 (1 = 실시간)")
    ] = params.DEFAULT_SPEED,
    duration: Annotated[
        float | None, typer.Option(min=0, help="실제 시간 기준 실행 초 (기본: 계속)")
    ] = None,
    max_visits: Annotated[
        int | None, typer.Option(min=1, help="이만큼 방문을 만들면 정상 종료 (기본: 계속)")
    ] = None,
    control_file: Annotated[
        Path,
        typer.Option(envvar="SIM_CONTROL_FILE", help="제어 신호 파일 (member live와 같은 파일)"),
    ] = Path(DEFAULT_CONTROL_FILE),
    seed: Annotated[int | None, typer.Option(help="기본 시드 (기본: SIM_SEED, 없으면 42)")] = None,
    run_salt: Annotated[
        int | None, typer.Option(help="실행 구분값 (기본: 시작 시각의 epoch 초)")
    ] = None,
    click_sink: Annotated[
        str, typer.Option(help=f"클릭 로그 출력 ({' | '.join(CLICK_SINKS)})")
    ] = "none",
    click_file: Annotated[Path, typer.Option(help="--click-sink jsonl일 때 파일 경로")] = Path(
        params.DEFAULT_CLICK_FILE
    ),
) -> None:
    """방문 → 조회 → 장바구니 → 주문 → 결제 → 상태 전이를 만들어 주문 테이블에 쓴다."""
    if mode not in MODES:
        raise _fail(f"--mode는 {', '.join(MODES)} 중 하나여야 합니다.")
    if click_sink not in CLICK_SINKS:
        raise _fail(f"--click-sink는 {', '.join(CLICK_SINKS)} 중 하나여야 합니다.")
    try:
        config = load_config()
        check_db_target(config.database_url, os.environ.get(ALLOW_REMOTE_ENV) == "1")
    except (ConfigError, DatabaseTargetError) as error:
        raise _fail(str(error)) from None
    seed = config.seed if seed is None else seed
    clock = SimClock(speed=speed)
    run_salt = int(clock.now().timestamp()) if run_salt is None else run_salt

    clicks: ClickSink = NullClickSink() if click_sink == "none" else JsonlClickSink(click_file)
    click_label = "none" if click_sink == "none" else f"jsonl ({click_file})"
    typer.echo(f"대상 DB: {describe_target(config.database_url)}")
    typer.echo(
        f"모드: {mode}  배속: {speed:g}  하루 방문: {visits_daily:,.0f}  시드: {seed}  "
        f"run_salt: {run_salt}  클릭 Sink: {click_label}  제어 파일: {control_file}"
    )
    orders = DbOrderSink(config.database_url)
    runner = BehaviorRunner(
        orders,
        clicks,
        DbMemberSource(config.database_url),
        DbCatalogSource(config.database_url),
        clock,
        FileControlSource(control_file, warn=lambda m: typer.echo(f"경고: {m}", err=True)),
        seed=seed,
        run_salt=run_salt,
        mode=mode,
        visits_daily=visits_daily,
        duration=duration,
        max_visits=max_visits,
        out=typer.echo,
    )
    try:
        with stop_on_signals(runner):
            summary = runner.run()
    except (SafeDatabaseError, BehaviorError) as error:
        raise _fail(str(error)) from None
    finally:
        orders.close()
        clicks.close()
    typer.echo("")
    for line in summary.lines():
        typer.echo(line)
