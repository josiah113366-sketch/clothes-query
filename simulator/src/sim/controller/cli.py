"""sim controller: serve(서버)와 서버를 HTTP로 부르는 얇은 클라이언트 명령.

제어 파일과 정답표를 쓰는 곳은 서버 하나다. 클라이언트 명령은 파일을 직접 쓰지 않는다.
토큰, 접속 문자열, 버킷 이름은 출력하지 않는다.
"""

import json
import os
import signal
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Annotated

import typer

from sim.common.config import ConfigError, load_config
from sim.common.control import DEFAULT_CONTROL_FILE, MODES
from sim.common.db import DatabaseTargetError, check_db_target
from sim.common.rng import SimRandom, derive_seed
from sim.common.stats import stats_path
from sim.controller.control_writer import FileControlWriter
from sim.controller.log import DEFAULT_INCIDENT_DIR, FileIncidentLog, IncidentLog, S3IncidentLog
from sim.controller.model import (
    DEFAULT_BURST_MINUTES,
    DEFAULT_MEDIUM_MINUTES,
    DEFAULT_PG_EXTRA_FAIL,
    DEFAULT_PG_OUTAGE_MINUTES,
    DEFAULT_POLLUTION_COUNT,
    DEFAULT_SINK_PAUSE_MINUTES,
    ORDER_TOTAL_MISMATCH,
    SINK_CONNECTORS,
)
from sim.controller.pollution import DbPollution
from sim.controller.server import ControllerServer, ServerConfigError
from sim.controller.service import ControllerService
from sim.controller.traffic import TrafficMonitor, http_fetcher

app = typer.Typer(help="모드 전환, 장애 주입, 정답표 기록 (운영자용)", no_args_is_help=True)

TOKEN_ENV = "SIM_CONTROLLER_TOKEN"
DEFAULT_URL = "http://127.0.0.1:8080"
INCIDENT_LOGS = ("file", "s3")
UrlOption = Annotated[
    str, typer.Option("--url", envvar="SIM_CONTROLLER_URL", help="컨트롤러 서버 주소")
]


def _fail(message: str) -> typer.Exit:
    typer.echo(f"오류: {message}", err=True)
    return typer.Exit(1)


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(envvar="SIM_CONTROLLER_HOST", help="여는 주소 (로컬 밖이면 토큰 필요)")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="SIM_CONTROLLER_PORT", min=0, max=65535)] = 8080,
    control_file: Annotated[
        Path, typer.Option(envvar="SIM_CONTROL_FILE", help="member·behavior live가 읽는 제어 파일")
    ] = Path(DEFAULT_CONTROL_FILE),
    incident_log: Annotated[str, typer.Option(help="정답표 위치 (file | s3)")] = "file",
    incident_dir: Annotated[Path, typer.Option(help="file일 때 폴더")] = Path(DEFAULT_INCIDENT_DIR),
    medium_minutes: Annotated[
        float, typer.Option(envvar="SIM_MEDIUM_MINUTES", min=0.001, help="medium 자동 복귀(분)")
    ] = DEFAULT_MEDIUM_MINUTES,
    burst_minutes: Annotated[
        float, typer.Option(envvar="SIM_BURST_MINUTES", min=0.001, help="burst 자동 복귀(분)")
    ] = DEFAULT_BURST_MINUTES,
) -> None:
    """컨트롤러 서버를 켠다. SIGINT/SIGTERM이면 진행 중 사건을 끝내고 종료 코드 0으로 끝난다."""
    if incident_log not in INCIDENT_LOGS:
        raise _fail("--incident-log는 file 또는 s3여야 합니다.")
    token = os.environ.get(TOKEN_ENV, "").strip() or None
    try:
        config = load_config(require_database=False)
    except ConfigError as error:
        raise _fail(str(error)) from None

    log: IncidentLog
    if incident_log == "s3":
        if not config.s3_bucket:
            raise _fail("--incident-log s3에는 S3_BUCKET이 필요합니다.")
        log = S3IncidentLog(config.s3_bucket, region=config.aws_region or None)
        log_label = "s3 (ground_truth/incident_log/)"
    else:
        log = FileIncidentLog(incident_dir)
        log_label = f"폴더 {incident_dir}"

    pollution = None
    if config.database_url:
        try:
            check_db_target(config.database_url, os.environ.get("SIM_ALLOW_REMOTE_DB") == "1")
        except DatabaseTargetError as error:
            raise _fail(str(error)) from None
        pollution = DbPollution(config.database_url, config.seed)

    ids = SimRandom(derive_seed(config.seed, "controller", time.time_ns()))
    service = ControllerService(
        FileControlWriter(control_file),
        log,
        pollution,
        lambda: datetime.now(UTC),
        ids.uuid4,
        medium_minutes=medium_minutes,
        burst_minutes=burst_minutes,
    )
    try:
        api_url = os.environ.get("SIM_API_URL", "").strip()
        traffic = TrafficMonitor(
            {name: stats_path(control_file, name) for name in ("behavior", "member")},
            http_fetcher(api_url) if api_url else None,
        )
        server = ControllerServer(service, host, port, token, traffic)
    except ServerConfigError as error:
        raise _fail(str(error)) from None
    except OSError as error:
        raise _fail(f"{host}:{port}을(를) 열지 못했습니다 ({type(error).__name__})") from None

    stop = threading.Event()

    def handler(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous = {s: signal.signal(s, handler) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        server.start()
        typer.echo(f"컨트롤러: http://{host}:{server.port}  (토큰 {'사용' if token else '없음'})")
        typer.echo(
            f"제어 파일: {control_file.name}  정답표: {log_label}  "
            f"자동 복귀: medium {medium_minutes:g}분, burst {burst_minutes:g}분  "
            f"데이터 오염: {'켜짐' if pollution else '꺼짐 (DATABASE_URL 없음)'}"
        )
        while not stop.wait(0.5):
            pass
    finally:
        server.stop()
        for s, old in previous.items():
            signal.signal(s, old)
    typer.echo("종료: 진행 중 사건을 끝내고 제어 파일을 normal로 되돌렸습니다.")


# --- 서버를 부르는 얇은 클라이언트 ---


def _call(url: str, method: str, path: str, body: dict | None = None) -> None:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url.rstrip("/") + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read() or b"{}").get("error", "")
        except json.JSONDecodeError:
            message = ""
        raise _fail(f"{error.code} {message}".strip()) from None
    except (urllib.error.URLError, OSError):
        raise _fail(
            "컨트롤러 서버에 연결하지 못했습니다. sim controller serve가 켜져 있는지 확인하세요."
        ) from None
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def status(url: UrlOption = DEFAULT_URL) -> None:
    """현재 상태를 본다."""
    _call(url, "GET", "/api/status")


@app.command()
def mode(
    value: Annotated[str, typer.Argument(metavar="MODE", help=" | ".join(MODES))],
    url: UrlOption = DEFAULT_URL,
) -> None:
    """모드를 바꾼다 (medium·burst는 자동으로 normal로 돌아온다)."""
    _call(url, "POST", "/api/mode", {"mode": value})


@app.command()
def running(
    value: Annotated[str, typer.Argument(metavar="true|false")],
    url: UrlOption = DEFAULT_URL,
) -> None:
    """새 가입·방문을 멈추거나(false) 다시 켠다(true)."""
    if value not in ("true", "false"):
        raise _fail("true 또는 false여야 합니다.")
    _call(url, "POST", "/api/running", {"running": value == "true"})


@app.command("pg-outage")
def pg_outage(
    pg: Annotated[str, typer.Option(help="PG_A | PG_B")],
    extra_fail: Annotated[
        float, typer.Option(help="추가 실패율 (0 초과 1 이하)")
    ] = DEFAULT_PG_EXTRA_FAIL,
    minutes: Annotated[
        float, typer.Option(help="지속 시간(분, 최대 60)")
    ] = DEFAULT_PG_OUTAGE_MINUTES,
    url: UrlOption = DEFAULT_URL,
) -> None:
    """PG 장애를 시작한다."""
    _call(
        url,
        "POST",
        "/api/incidents/pg-outage",
        {"pg": pg, "extra_fail": extra_fail, "minutes": minutes},
    )


@app.command()
def pollution(
    kind: Annotated[str, typer.Option(help="ORDER_TOTAL_MISMATCH | DUPLICATE_SUCCESS_PAYMENT")] = (
        ORDER_TOTAL_MISMATCH
    ),
    count: Annotated[int, typer.Option(help="건수 (최대 500)")] = DEFAULT_POLLUTION_COUNT,
    url: UrlOption = DEFAULT_URL,
) -> None:
    """데이터 오염을 만든다 (DB 제약은 통과하지만 업무 규칙을 어기는 행)."""
    _call(url, "POST", "/api/incidents/data-pollution", {"kind": kind, "count": count})


@app.command("sink-pause")
def sink_pause(
    connector: Annotated[str, typer.Option(help=" | ".join(SINK_CONNECTORS))] = (
        SINK_CONNECTORS[0]
    ),
    minutes: Annotated[
        float, typer.Option(help="계획한 정지 시간(분, 최대 60). 자동 종료하지 않는다")
    ] = DEFAULT_SINK_PAUSE_MINUTES,
    url: UrlOption = DEFAULT_URL,
) -> None:
    """S3 Sink 정지의 시작 기록만 남긴다. 정지·재개는 kubectl, 재개 확인 뒤 end."""
    _call(url, "POST", "/api/incidents/sink-pause", {"connector": connector, "minutes": minutes})


@app.command()
def end(url: UrlOption = DEFAULT_URL) -> None:
    """진행 중 사건을 끝낸다."""
    _call(url, "POST", "/api/incidents/end", {})
