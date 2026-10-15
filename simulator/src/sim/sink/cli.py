"""sim sink: 로컬 S3 Sink 커넥터 등록·상태·검증·초기화. 출력에 회원 값, 자격 증명, 버킷 이름을 싣지 않는다."""

import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from confluent_kafka import ConsumerGroupTopicPartitions, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient

from sim.cdc import consume
from sim.cdc.connect import (
    ConfigFileError,
    ConnectClient,
    ConnectError,
    load_connector_config,
    states,
    wait_running,
)
from sim.common.config import Config, ConfigError, load_config
from sim.common.regions import RegionFileError, load_regions
from sim.sink import checks, params
from sim.sink.s3 import S3Error, S3Reader

app = typer.Typer(help="로컬 S3 Sink(Kafka → S3) 설정과 확인", no_args_is_help=True)

IN_PROGRESS_EXIT = 2


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


def _config() -> Config:
    try:
        return load_config(require_database=False)
    except ConfigError as error:
        raise _fail(str(error)) from None


def _reader(config: Config) -> S3Reader:
    try:
        return S3Reader(config.s3_bucket, config.aws_region)
    except S3Error as error:
        raise _fail(str(error)) from None


def _print_connector_status(status: dict) -> None:
    connector, tasks = states(status)
    typer.echo(f"커넥터: {params.CONNECTOR_NAME} {connector}  task: {', '.join(tasks) or '없음'}")


def _source_topic(config_path: Path) -> str:
    source = load_connector_config(config_path.parent / "member-source.json")
    return str(source.get("transforms.route.replacement", ""))


def _group_lag(bootstrap: str) -> int | None:
    """토픽 끝 offset − 커넥터(소비자 그룹)가 커밋한 offset. 그룹이 아직 없으면 None."""
    offsets = consume.partition_offsets(bootstrap, params.TOPIC)
    if not offsets:
        return None
    admin = AdminClient({"bootstrap.servers": bootstrap})
    request = [
        ConsumerGroupTopicPartitions(
            params.CONSUMER_GROUP, [TopicPartition(params.TOPIC, p) for p in offsets]
        )
    ]
    try:
        result = admin.list_consumer_group_offsets(request)[params.CONSUMER_GROUP].result(
            timeout=15
        )
    except KafkaException:
        return None
    committed = {tp.partition: tp.offset for tp in result.topic_partitions if tp.offset >= 0}
    if not committed:
        return None
    return sum(max(high - committed.get(p, low), 0) for p, (low, high) in offsets.items())


@app.command()
def setup(
    config_path: Annotated[Path, typer.Option("--config", help="커넥터 설정 파일")] = Path(
        params.DEFAULT_CONFIG_PATH
    ),
) -> None:
    """S3 Sink 커넥터를 등록한다 (이미 있으면 바꾸지 않고 상태만 보여 준다)."""
    config = _config()
    try:
        connector_config = load_connector_config(config_path)
        problems = checks.config_problems(connector_config, _source_topic(config_path))
    except ConfigFileError as error:
        raise _fail(str(error)) from None
    if problems:
        detail = "\n".join(f"- {p}" for p in problems)
        raise _fail(f"커넥터 설정이 안전장치를 통과하지 못했습니다. 등록하지 않았습니다.\n{detail}")

    reader = _reader(config)
    if not config.aws_region:
        raise _fail("AWS_REGION이 설정되지 않았습니다 (simulator/.env).")
    # Connect 컨테이너는 compose가 .env에서 넘긴 환경 변수 키만 쓴다. 여기서 ~/.aws 같은 다른 출처로
    # S3 접근이 되더라도 커넥터는 실패하므로, 환경 변수에 키가 있는지 이름만 확인한다.
    missing = [n for n in params.CREDENTIAL_ENV_NAMES if not os.environ.get(n)]
    if missing:
        raise _fail(
            f"simulator/.env에 {', '.join(missing)}이(가) 없습니다. 커넥터는 이 환경 변수의 키만 쓰므로 "
            "`.env`에 넣고 `docker compose --profile cdc up -d connect`로 Connect를 다시 띄우세요."
        )
    try:
        reader.check_access()
    except S3Error as error:
        raise _fail(f"S3 접근 확인에 실패했습니다: {error}") from None
    typer.echo(f"S3 접근 확인: 통과 (버킷 조회, {params.PATH_PREFIX}/ 경로 조회)")

    client = ConnectClient(config.connect_url)
    name = str(connector_config["name"])
    try:
        client.ping()
        typer.echo(f"Kafka Connect: {config.connect_url} 연결됨")
        if not any(c.endswith("S3SinkConnector") for c in client.plugin_classes()):
            raise _fail(
                "Connect에 S3 Sink 플러그인이 없습니다. "
                "`docker compose --profile cdc build connect` 후 `up -d connect`로 다시 띄우세요."
            )
        existing = client.status_or_none(name)
        if existing is not None:
            typer.echo("같은 이름의 커넥터가 이미 있어 아무것도 바꾸지 않았습니다.")
            _print_connector_status(existing)
            typer.echo("설정을 바꾸려면 `sim sink reset` 후 다시 `sim sink setup`을 하세요.")
            return
        client.create(connector_config)
        typer.echo(
            f"커넥터 {name}을 등록했습니다. RUNNING을 기다립니다 (최대 {params.SETUP_WAIT_SECONDS}초)."
        )
        status = wait_running(client, name, timeout=params.SETUP_WAIT_SECONDS)
    except ConnectError as error:
        raise _fail(str(error)) from None
    _print_connector_status(status)
    if "FAILED" in states(status)[1] or states(status)[0] == "FAILED":
        raise _fail("커넥터가 실패했습니다. `docker compose logs connect`로 로그를 확인하세요.")
    typer.echo("`sim sink status`로 S3에 파일이 생기는지 보세요.")


@app.command()
def status() -> None:
    """커넥터, 밀린 양, S3 파일 현황을 보여 준다 (읽기 전용, 객체 내용은 읽지 않는다)."""
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
        lag = _group_lag(config.kafka_bootstrap)
    except consume.ConsumeError as error:
        raise _fail(str(error)) from None
    typer.echo(f"밀린 양: {'아직 읽은 기록 없음' if lag is None else f'{lag:,}건'}")

    reader = _reader(config)
    try:
        objects = list(reader.list_objects(params.TOPIC_PREFIX_PATH))
        block = reader.public_access_block()
    except S3Error as error:
        raise _fail(f"S3 조회에 실패했습니다: {error}") from None
    typer.echo(f"버킷 공개 설정: {block}")
    if not objects:
        typer.echo(f"S3 {params.TOPIC_PREFIX_PATH}: 파일 없음")
        return
    by_dt: dict[str, list] = defaultdict(list)
    for obj in objects:
        parsed = checks.parse_key(obj.key)
        by_dt[
            f"year={parsed.dt:%Y}/month={parsed.dt:%m}/day={parsed.dt:%d}"
            if parsed
            else "(형식 밖)"
        ].append(obj)
    typer.echo(f"S3 {params.TOPIC_PREFIX_PATH}")
    for folder, items in sorted(by_dt.items()):
        newest = max(item.last_modified for item in items).astimezone(UTC)
        typer.echo(
            f"  {folder}: 파일 {len(items):,}개, {sum(i.size for i in items):,} bytes, "
            f"가장 최근 {newest:%Y-%m-%d %H:%M:%S}Z"
        )


@app.command()
def reset(
    yes: Annotated[bool, typer.Option("--yes", help="확인 질문을 건너뛴다")] = False,
) -> None:
    """커넥터와 읽은 위치를 지운다. S3 객체는 건드리지 않는다."""
    config = _config()
    if not yes and not typer.confirm(
        "S3 Sink 커넥터와 소비자 그룹 offset을 지웁니다 (S3 파일은 그대로). 계속할까요?",
        default=False,
    ):
        raise typer.Exit(1)
    client = ConnectClient(config.connect_url)
    name = params.CONNECTOR_NAME
    try:
        if client.exists(name):
            client.stop(name)
            client.delete_offsets(name)  # 안 지우면 같은 이름으로 다시 만들 때 이어서 읽는다
            client.delete(name)
            typer.echo("커넥터를 정지하고 offset을 지운 뒤 삭제했습니다.")
        else:
            typer.echo("커넥터가 없어 건너뜁니다.")
    except ConnectError as error:
        raise _fail(str(error)) from None
    typer.echo(
        "S3에는 파일이 그대로 남아 있습니다. 지우려면 직접 실행하세요 (이 명령은 실행하지 않습니다):"
    )
    typer.echo(f"  aws s3 rm s3://${{{params.BUCKET_ENV}}}/{params.TOPIC_PREFIX_PATH} --recursive")
    typer.echo(
        "주의: reset 뒤 다시 `sim sink setup`하면 토픽을 처음부터 다시 읽어 "
        "같은 데이터가 S3에 한 번 더 쌓입니다."
    )


@app.command()
def verify() -> None:
    """S3 파일을 읽어 11개 항목을 확인한다 (읽기 전용). 실패하면 종료 코드 1, 아직 쓰는 중이면 2."""
    config = _config()
    try:
        regions = load_regions(config.region_file)
    except RegionFileError as error:
        raise _fail(str(error)) from None
    reader = _reader(config)
    client = ConnectClient(config.connect_url)

    try:
        connector_status = client.status_or_none(params.CONNECTOR_NAME)
        registered = (
            client.get_config(params.CONNECTOR_NAME) if connector_status is not None else None
        )
        lag = _group_lag(config.kafka_bootstrap)
        offsets = consume.partition_offsets(config.kafka_bootstrap, params.TOPIC)
        objects = sorted(reader.list_objects(params.TOPIC_PREFIX_PATH), key=lambda o: o.key)
    except (ConnectError, consume.ConsumeError, S3Error) as error:
        raise _fail(str(error)) from None
    if not offsets:
        raise _fail(f"토픽 {params.TOPIC}이 없습니다.")

    last_modified = max((o.last_modified for o in objects), default=None)
    reason = checks.writing_in_progress(lag, last_modified, datetime.now(UTC))
    if reason is not None:
        typer.echo(f"아직 쓰는 중입니다 ({reason}). 잠시 뒤 다시 실행하세요.")
        raise typer.Exit(IN_PROGRESS_EXIT)

    typer.echo(f"토픽 {params.TOPIC}의 member_id를 읽습니다 (읽어도 offset은 남기지 않습니다).")
    topic_ids: set[str] = set()
    try:
        for message in consume.iter_messages(config.kafka_bootstrap, params.TOPIC):
            parsed = checks.key_member_id(message.key)
            if parsed:
                topic_ids.add(parsed)
    except consume.ConsumeError as error:
        raise _fail(str(error)) from None

    checker = checks.SinkChecker(offsets, regions.names, datetime.now(UTC).date())
    typer.echo(f"S3 파일 {len(objects):,}개를 읽습니다 (파일로 저장하지 않습니다).")
    try:
        for index, obj in enumerate(objects, start=1):
            checker.add_file(obj, reader.iter_lines(obj.key))
            if index % 50 == 0:
                typer.echo(f"  {index:,}개 읽음")
    except S3Error as error:
        raise _fail(str(error)) from None

    results = [
        checks.check_connector(connector_status, registered, params.TOPIC),
        *checker.results(topic_ids),
    ]
    results.sort(key=lambda r: r.number)
    typer.echo("")
    typer.echo("| # | 확인 | 결과 | 상세 |")
    typer.echo("|---|---|---|---|")
    for r in results:
        label = "건너뜀" if r.skipped else "통과" if r.passed else "실패"
        typer.echo(f"| {r.number} | {r.name} | {label} | {r.detail} |")
    failed = [r for r in results if not r.passed]
    typer.echo(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    if failed:
        raise typer.Exit(1)
