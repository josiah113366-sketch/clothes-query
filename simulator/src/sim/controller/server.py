"""컨트롤러 HTTP 서버 (표준 라이브러리). 운영자용 버튼 화면과 JSON API.

- /api/*는 Authorization: Bearer <SIM_CONTROLLER_TOKEN>이 필요하다. 로컬 바인딩에서만 토큰 없이 켤 수 있다.
- 응답 본문에 DB 오류 내용, 접속 정보, 토큰을 싣지 않는다.
- 백그라운드 스레드가 1초마다 service.tick()을 부른다 (자동 복귀, 끝 기록 재시도).
- traffic이 있으면 다른 스레드가 2초마다 표본을 만든다. GET /api/traffic?since=<epoch 초>로 받는다.
"""

import hmac
import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from sim.controller.log import IncidentLogError
from sim.controller.page import PAGE
from sim.controller.service import (
    ApplyError,
    ControllerService,
    IncidentActiveError,
    InvalidRequestError,
    UnavailableError,
)
from sim.controller.traffic import SAMPLE_SECONDS, TrafficMonitor

LOCAL_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_BODY_BYTES = 10_000
TICK_SECONDS = 1.0


class ServerConfigError(RuntimeError):
    """서버를 켤 수 없는 설정. 메시지에 토큰이나 접속 정보를 싣지 않는다."""


def check_bind(host: str, token: str | None) -> None:
    if not token and host not in LOCAL_BIND_HOSTS:
        raise ServerConfigError(
            "로컬(127.0.0.1)이 아닌 주소에 열려면 SIM_CONTROLLER_TOKEN이 필요합니다."
        )


def _since(query: str) -> float | None:
    values = parse_qs(query).get("since")
    try:
        return float(values[0]) if values else None
    except ValueError:
        return None


def _handler(
    service: ControllerService, token: str | None, traffic: TrafficMonitor | None
) -> type[BaseHTTPRequestHandler]:
    routes: dict[str, Callable[[dict], dict]] = {
        "/api/mode": lambda b: service.set_mode(b.get("mode")),
        "/api/running": lambda b: service.set_running(b.get("running")),
        "/api/incidents/pg-outage": lambda b: service.start_pg_outage(
            b.get("pg"), b.get("extra_fail", 0.85), b.get("minutes", 10)
        ),
        "/api/incidents/data-pollution": lambda b: service.start_data_pollution(
            b.get("kind", "ORDER_TOTAL_MISMATCH"), b.get("count", 30)
        ),
        "/api/incidents/sink-pause": lambda b: service.start_sink_pause(
            b.get("connector", "bronze-s3-sink-v2"), b.get("minutes", 25)
        ),
        "/api/incidents/end": lambda b: service.end_active("manual"),
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "sim-controller"

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif url.path == "/healthz":
                self._json(200, {"ok": True})
            elif url.path == "/api/status":
                if self._authorized():
                    self._json(200, service.status())
            elif url.path == "/api/traffic":
                if self._authorized():
                    if traffic is None:
                        self._json(200, {"samples": [], "api_configured": False})
                    else:
                        self._json(200, traffic.history(_since(url.query)))
            else:
                self._json(404, {"error": "없는 경로입니다."})

        def do_POST(self) -> None:
            action = routes.get(self.path)
            if action is None:
                self._json(404, {"error": "없는 경로입니다."})
                return
            if not self._authorized():
                return
            try:
                body = self._read_body()
                self._json(200, action(body))
            except (InvalidRequestError, ValueError) as error:
                self._json(400, {"error": str(error)})
            except IncidentActiveError as error:
                self._json(409, {"error": str(error)})
            except IncidentLogError:
                self._json(503, {"error": "정답표를 기록하지 못해 아무것도 바꾸지 않았습니다."})
            except (UnavailableError, ApplyError) as error:
                self._json(503, {"error": str(error)})

        def _authorized(self) -> bool:
            if not token:
                return True
            given = self.headers.get("Authorization", "")
            if hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
                return True
            self._json(401, {"error": "토큰이 필요합니다."})
            return False

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                raise InvalidRequestError("요청 본문이 너무 큽니다.")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise InvalidRequestError("본문은 JSON이어야 합니다.") from None
            if not isinstance(body, dict):
                raise InvalidRequestError("본문은 JSON 객체여야 합니다.")
            return body

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(
            self, format: str, *args: object
        ) -> None:  # 요청 줄(헤더 포함)을 찍지 않는다
            pass

    return Handler


class ControllerServer:
    def __init__(
        self,
        service: ControllerService,
        host: str,
        port: int,
        token: str | None,
        traffic: TrafficMonitor | None = None,
    ) -> None:
        check_bind(host, token)
        self.service = service
        self.traffic = traffic
        self.httpd = ThreadingHTTPServer((host, port), _handler(service, token, traffic))
        self.httpd.daemon_threads = True
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def start(self) -> None:
        """제어 파일을 깨끗한 상태로 쓰고, 서버와 tick 스레드를 시작한다."""
        self.service.start()
        targets = [self.httpd.serve_forever, self._tick_loop]
        if self.traffic is not None:
            targets.append(self._traffic_loop)
        for target in targets:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)

    def _tick_loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.service.tick()
            except Exception as error:  # noqa: BLE001  tick 스레드는 죽지 않는다. 내용은 남기지 않는다
                self.service.last_error = f"tick 오류 ({type(error).__name__})"

    def _traffic_loop(self) -> None:
        assert self.traffic is not None
        while True:
            try:
                self.traffic.sample()
            except Exception as error:  # noqa: BLE001  표본 하나를 놓쳐도 화면만 한 칸 빈다
                self.service.last_error = f"트래픽 표본 오류 ({type(error).__name__})"
            if self._stop.wait(SAMPLE_SECONDS):
                return

    def stop(self) -> None:
        """진행 중 사건을 shutdown으로 끝내고 서버를 닫는다."""
        self._stop.set()
        self.service.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()
