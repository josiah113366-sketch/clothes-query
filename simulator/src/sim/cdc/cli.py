"""sim cdc: 로컬 Debezium 커넥터 등록·상태·초기화. 출력에 회원 값을 싣지 않는다."""

import time
from pathlib import Path
from typing import Annotated

import typer

from sim.cdc import checks, consume, dbcheck, params
from sim.cdc.connect import (
    ConfigFileError,
    ConnectClient,
    ConnectError,
    check_connector_config,
    load_connector_config,
    states,
    wait_running,
)
from sim.common.config import Config, ConfigError, load_config
from sim.common.db import SafeDatabaseError, connect, describe_target, safe_db_errors, target_host
from sim.common.regions import RegionFileError, load_regions

app = typer.Typer(help="로컬 CDC(Debezium → Kafka) 설정과 확인", no_args_is_help=True)

LOCAL_HOSTS = ("localhost", "127.0.0.1")


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as error:
        raise _fail(str(error)) from None


def _print_connector_status(status: dict) -> None:
    connector, tasks = states(status)
    typer.echo(f"커넥터: {params.CONNECTOR_NAME} {connector}  task: {', '.join(tasks) or '없음'}")


@app.command()
def setup(
    config_path: Annotated[Path, typer.Option("--config", help="커넥터 설정 파일")] = Path(
        params.DEFAULT_CONFIG_PATH
    ),
) -> None:
    """커넥터를 등록한다 (이미 있으면 바꾸지 않고 상태만 보여 준다)."""
    config = _config()
    try:
        connector_config = load_connector_config(config_path)
        check_connector_config(connector_config)
    except ConfigFileError as error:
        raise _fail(
            f"커넥터 설정이 안전장치를 통과하지 못했습니다. 등록하지 않았습니다.\n{error}"
        ) from None

    typer.echo(f"대상 DB: {describe_target(config.database_url)}")
    try:
        with connect(config.database_url) as conn:
            rows = dbcheck.member_count(conn)
    except SafeDatabaseError as error:
        raise _fail(str(error)) from None
    if rows == 0:
        raise _fail("member 행이 0입니다. 베이스라인을 먼저 적재하세요 (sim member baseline).")

    client = ConnectClient(config.connect_url)
    name = str(connector_config["name"])
    try:
        client.ping()
        typer.echo(f"Kafka Connect: {config.connect_url} 연결됨")
        existing = client.status_or_none(name)
        if existing is not None:
            typer.echo("같은 이름의 커넥터가 이미 있어 아무것도 바꾸지 않았습니다.")
            _print_connector_status(existing)
            typer.echo("설정을 바꾸려면 `sim cdc reset` 후 다시 `sim cdc setup`을 하세요.")
            return
        client.create(connector_config)
        typer.echo(
            f"커넥터 {name}을 등록했습니다. RUNNING을 기다립니다 (최대 {params.SETUP_WAIT_SECONDS}초)."
        )
        status = wait_running(client, name)
    except ConnectError as error:
        raise _fail(str(error)) from None
    _print_connector_status(status)
    if "FAILED" in states(status)[1] or states(status)[0] == "FAILED":
        raise _fail("커넥터가 실패했습니다. `docker compose logs connect`로 로그를 확인하세요.")
    typer.echo("스냅샷은 백그라운드로 진행됩니다. `sim cdc status`로 진행을 보세요.")


@app.command()
def status() -> None:
    """커넥터, 복제 슬롯, publication, 토픽 offset을 보여 준다 (읽기 전용)."""
    config = _config()
    client = ConnectClient(config.connect_url)
    try:
        current = client.status_or_none(params.CONNECTOR_NAME)
        if current is None:
            typer.echo(f"커넥터: {params.CONNECTOR_NAME} 없음")
        else:
            _print_connector_status(current)
    except ConnectError as error:
        typer.echo(f"커넥터: 확인 못 함 ({error})")

    try:
        with connect(config.database_url) as conn:
            slot = dbcheck.slot_info(conn)
            tables = dbcheck.publication_tables(conn)
    except SafeDatabaseError as error:
        raise _fail(str(error)) from None
    if slot is None:
        typer.echo(f"슬롯: {params.SLOT_NAME} 없음")
    else:
        typer.echo(
            f"슬롯: {params.SLOT_NAME} ({slot.plugin}) 활성={'예' if slot.active else '아니오'} "
            f"밀린 WAL {slot.lag_bytes:,} bytes"
        )
    typer.echo(f"publication {params.PUBLICATION_NAME}: {', '.join(tables) or '없음'}")

    try:
        offsets = consume.partition_offsets(config.kafka_bootstrap, params.TOPIC)
    except consume.ConsumeError as error:
        raise _fail(str(error)) from None
    if not offsets:
        typer.echo(f"토픽 {params.TOPIC}: 없음")
        return
    detail = ", ".join(f"{p}={high - low:,}" for p, (low, high) in sorted(offsets.items()))
    typer.echo(
        f"토픽 {params.TOPIC}: 파티션 {len(offsets)}개, 합계 {consume.total_messages(offsets):,}건 ({detail})"
    )


def _drop_slot_with_retry(database_url: str) -> bool:
    deadline = time.monotonic() + params.SLOT_DROP_RETRY_SECONDS
    while True:
        try:
            with safe_db_errors():
                conn = connect(database_url)
                conn.autocommit = True
                with conn:
                    return dbcheck.drop_slot(conn)
        except SafeDatabaseError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)  # 커넥터가 슬롯을 놓을 때까지 잠깐 걸릴 수 있다


@app.command()
def reset(
    yes: Annotated[bool, typer.Option("--yes", help="확인 질문을 건너뛴다")] = False,
) -> None:
    """커넥터·offset·슬롯·publication·토픽을 지운다 (로컬 전용). members 행은 건드리지 않는다."""
    config = _config()
    if target_host(config.database_url) not in LOCAL_HOSTS:
        raise _fail("로컬 DB(localhost, 127.0.0.1)가 아니면 reset하지 않습니다.")
    typer.echo(f"대상 DB: {describe_target(config.database_url)}")
    if not yes and not typer.confirm(
        "커넥터, 복제 슬롯, publication, 토픽을 지웁니다. 계속할까요?", default=False
    ):
        raise typer.Exit(1)

    client = ConnectClient(config.connect_url)
    name = params.CONNECTOR_NAME
    try:
        if client.exists(name):
            client.stop(name)
            client.delete_offsets(name)  # 안 지우면 같은 이름으로 다시 만들 때 스냅샷을 건너뛴다
            client.delete(name)
            typer.echo("커넥터를 정지하고 offset을 지운 뒤 삭제했습니다.")
        else:
            typer.echo("커넥터가 없어 건너뜁니다.")
    except ConnectError as error:
        raise _fail(str(error)) from None

    try:
        dropped = _drop_slot_with_retry(config.database_url)
        typer.echo(f"복제 슬롯 {params.SLOT_NAME}: {'삭제' if dropped else '없음'}")
        with safe_db_errors():
            conn = connect(config.database_url)
            conn.autocommit = True
            with conn:
                dbcheck.drop_publication(conn)
        typer.echo(f"publication {params.PUBLICATION_NAME}: 삭제(없으면 건너뜀)")
    except SafeDatabaseError as error:
        raise _fail(str(error)) from None

    try:
        removed = consume.delete_topics(
            config.kafka_bootstrap, [params.TOPIC, params.HEARTBEAT_TOPIC]
        )
    except consume.ConsumeError as error:
        raise _fail(str(error)) from None
    typer.echo(f"토픽 삭제: {', '.join(removed) or '없음'}")
    typer.echo("끝났습니다. 다시 하려면 `sim cdc setup`을 하세요.")


def _load_sample(conn, size: int) -> tuple[set[str], dict[str, dict]]:
    """DB 전체 member_id 집합과, 무작위 샘플 회원의 비교용 값 (PII 컬럼은 읽지 않는다)."""
    with safe_db_errors():
        ids = {str(r[0]) for r in conn.execute("SELECT member_id::text FROM members")}
        rows = conn.execute(
            "SELECT member_id::text, signup_at, created_at, region_sigungu, age_band, status "
            "FROM members ORDER BY random() LIMIT %s",
            (size,),
        ).fetchall()
    sample = {
        str(r[0]): {
            "signup_at": r[1],
            "created_at": r[2],
            "region_sigungu": r[3],
            "age_band": r[4],
            "status": r[5],
        }
        for r in rows
    }
    return ids, sample


@app.command()
def verify(
    snapshot_expected: Annotated[
        int, typer.Option(help="r 이벤트의 기대 건수")
    ] = params.DEFAULT_SNAPSHOT_EXPECTED,
    live_expected: Annotated[
        int | None, typer.Option(help="c 이벤트의 기대 건수 (주면 확인)")
    ] = None,
) -> None:
    """토픽과 DB를 읽어 13개 항목을 확인한다 (읽기 전용). 실패하면 종료 코드 1."""
    config = _config()
    try:
        regions = load_regions(config.region_file)
    except RegionFileError as error:
        raise _fail(str(error)) from None

    client = ConnectClient(config.connect_url)
    try:
        status = client.status_or_none(params.CONNECTOR_NAME)
        registered = client.get_config(params.CONNECTOR_NAME) if status is not None else None
    except ConnectError as error:
        raise _fail(str(error)) from None

    try:
        with connect(config.database_url) as conn:
            slot = dbcheck.slot_info(conn)
            tables = dbcheck.publication_tables(conn)
            db_ids, sample = _load_sample(conn, params.SAMPLE_SIZE)
    except SafeDatabaseError as error:
        raise _fail(str(error)) from None

    checker = checks.EventChecker(
        regions.names,
        sample.keys(),
        snapshot_expected=snapshot_expected,
        live_expected=live_expected,
    )
    typer.echo(f"토픽 {params.TOPIC}을 처음부터 읽습니다 (읽어도 offset은 남기지 않습니다).")
    try:
        for message in consume.iter_messages(config.kafka_bootstrap, params.TOPIC):
            checker.add(message.key, message.value)
            if checker.total % 20_000 == 0:
                typer.echo(f"  {checker.total:,}건 읽음")
    except consume.ConsumeError as error:
        raise _fail(str(error)) from None
    typer.echo(f"  모두 읽음: {checker.total:,}건")

    results = [
        checks.check_connector(status, registered),
        checks.check_db_side(slot.plugin if slot else None, bool(slot and slot.active), tables),
        *checker.results(),
        checks.compare_member_ids(checker.all_ids, db_ids),
        checks.compare_sample(checker.sample_events, sample),
    ]
    results.sort(key=lambda r: r.number)

    typer.echo("")
    typer.echo("| # | 확인 | 결과 | 상세 |")
    typer.echo("|---|---|---|---|")
    for r in results:
        label = "건너뜀" if r.skipped else "통과" if r.passed else "실패"
        typer.echo(f"| {r.number} | {r.name} | {label} | {r.detail} |")
    failed = [r for r in results if not r.passed]
    applicable = [r for r in results if not r.skipped]
    typer.echo(
        f"\n{len(applicable) - len(failed)}/{len(applicable)} 통과 (전체 13항목 중 해당 {len(applicable)}항목)"
    )
    if failed:
        raise typer.Exit(1)
