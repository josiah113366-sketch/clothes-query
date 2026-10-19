"""sim clickstream: 클릭 로그 토픽 만들기·상태·검증·지우기.

setup과 reset은 로컬 부트스트랩(localhost, 127.0.0.1)에서만 한다. EKS의 토픽은 인프라가 만든다.
출력에 브로커 주소와 메시지 내용(member_id 등)을 싣지 않는다. 틀린 메시지는 파티션·offset만 알린다.
"""

from typing import Annotated

import typer

from sim.clickstream import topic as kafka_topic
from sim.clickstream.topic import TopicError
from sim.clickstream.verify import CHECKS, verify
from sim.common.config import ConfigError, load_config
from sim.common.kafka import (
    CLICK_TOPIC,
    CLICK_TOPIC_PARTITIONS,
    TOPIC_RETENTION_MS,
    KafkaSettings,
    load_kafka_settings,
)

app = typer.Typer(help="클릭 로그 토픽(clickstream) 만들기·상태·검증", no_args_is_help=True)

EMPTY_EXIT = 2


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


def _settings() -> KafkaSettings:
    try:
        load_config(require_database=False)  # simulator/.env를 읽어 둔다
        return load_kafka_settings()
    except ConfigError as error:
        raise _fail(str(error)) from None


def _require_local(settings: KafkaSettings, action: str) -> None:
    if not settings.is_local:
        raise _fail(
            f"{action}은(는) 로컬 Kafka(localhost, 127.0.0.1)에서만 합니다. "
            "원격 토픽은 인프라에서 관리합니다."
        )


@app.command()
def setup() -> None:
    """토픽이 없으면 만든다 (파티션 3, 복제 1, 보관 72시간). 있으면 그대로 둔다."""
    settings = _settings()
    _require_local(settings, "토픽 만들기")
    try:
        info = kafka_topic.describe(settings, CLICK_TOPIC)
        if info is None:
            kafka_topic.create(settings, CLICK_TOPIC, CLICK_TOPIC_PARTITIONS)
            typer.echo(
                f"토픽 {CLICK_TOPIC}을(를) 만들었습니다 "
                f"(파티션 {CLICK_TOPIC_PARTITIONS}, retention.ms={TOPIC_RETENTION_MS})."
            )
            return
    except TopicError as error:
        raise _fail(str(error)) from None
    typer.echo(f"토픽 {CLICK_TOPIC}이(가) 이미 있습니다. 바꾸지 않습니다.")
    if info.partitions != CLICK_TOPIC_PARTITIONS:
        typer.echo(f"주의: 파티션이 {info.partitions}개입니다 (기대 {CLICK_TOPIC_PARTITIONS}개).")
    if info.retention_ms != str(TOPIC_RETENTION_MS):
        typer.echo(f"주의: retention.ms가 {info.retention_ms}입니다 (기대 {TOPIC_RETENTION_MS}).")


@app.command()
def status() -> None:
    """토픽 존재 여부, 파티션별 low/high offset과 합계."""
    settings = _settings()
    try:
        info = kafka_topic.describe(settings, CLICK_TOPIC)
        if info is None:
            raise _fail(
                f"토픽 {CLICK_TOPIC}이(가) 없습니다. `sim clickstream setup`을 먼저 실행하세요."
            )
        offsets = kafka_topic.offsets(settings, CLICK_TOPIC, info.partitions)
    except TopicError as error:
        raise _fail(str(error)) from None
    typer.echo(f"토픽: {CLICK_TOPIC}  파티션: {info.partitions}  retention.ms: {info.retention_ms}")
    for partition, (low, high) in sorted(offsets.items()):
        typer.echo(f"  파티션 {partition}: low {low:,}  high {high:,}  ({high - low:,}건)")
    total = sum(high - low for low, high in offsets.values())
    typer.echo(f"합계: {total:,}건")


@app.command("verify")
def verify_command() -> None:
    """토픽을 처음부터 현재 끝까지 한 번 읽어 내용·순서·중복을 확인한다 (offset 저장 없음)."""
    settings = _settings()
    try:
        info = kafka_topic.describe(settings, CLICK_TOPIC)
        if info is None:
            raise _fail(f"토픽 {CLICK_TOPIC}이(가) 없습니다.")
        offsets = kafka_topic.offsets(settings, CLICK_TOPIC, info.partitions)
        report = verify(kafka_topic.read_all(settings, CLICK_TOPIC, offsets))
    except TopicError as error:
        raise _fail(str(error)) from None

    if report.empty:
        typer.echo(f"토픽 {CLICK_TOPIC}이(가) 비어 있습니다 (메시지 0건).")
        raise typer.Exit(EMPTY_EXIT)
    typer.echo(f"읽은 메시지: {report.total:,}건")
    for number, (name, label) in enumerate(CHECKS, start=1):
        result = report.results[name]
        if result.passed:
            typer.echo(f"  {number}. 통과  {label}")
        else:
            where = ", ".join(result.locations)
            typer.echo(f"  {number}. 실패  {label}: {result.failed:,}건 (예: {where})")
    if not report.passed:
        raise typer.Exit(1)
    typer.echo("모두 통과")


@app.command()
def reset(
    yes: Annotated[bool, typer.Option("--yes", help="정말 지운다")] = False,
) -> None:
    """토픽을 지운다 (--yes 필요, 로컬에서만)."""
    if not yes:
        raise _fail("토픽을 지우려면 --yes를 붙이세요.")
    settings = _settings()
    _require_local(settings, "토픽 지우기")
    try:
        if kafka_topic.describe(settings, CLICK_TOPIC) is None:
            typer.echo(f"토픽 {CLICK_TOPIC}이(가) 없습니다. 지울 것이 없습니다.")
            return
        kafka_topic.delete(settings, CLICK_TOPIC)
    except TopicError as error:
        raise _fail(str(error)) from None
    typer.echo(f"토픽 {CLICK_TOPIC}을(를) 지웠습니다.")
