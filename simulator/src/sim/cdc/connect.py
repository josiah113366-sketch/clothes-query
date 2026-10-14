"""Kafka Connect REST 호출(표준 라이브러리 urllib만 사용)과 커넥터 설정 파일 검사.

오류 메시지에는 HTTP 상태와 Connect가 준 짧은 설명만 싣는다. 회원 값은 이 모듈을 지나가지 않는다.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sim.cdc import params

Transport = Callable[[str, str, Mapping[str, Any] | None], tuple[int, Any]]
_PASSWORD_REFERENCE = re.compile(r"\$\{env:[A-Za-z_][A-Za-z0-9_]*\}")
_MAX_ERROR_TEXT = 300


class ConnectError(RuntimeError):
    """Connect 호출 실패. 메시지에 접속 비밀과 회원 값을 담지 않는다."""


class ConfigFileError(ValueError):
    """커넥터 설정 파일이 안전장치를 통과하지 못했다. 메시지는 이유 목록이다."""


# --- 설정 파일 검사 (안전장치) ---


def load_connector_config(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigFileError(f"설정 파일이 없습니다: {path}") from None
    except (OSError, ValueError):
        raise ConfigFileError(f"설정 파일을 읽을 수 없습니다: {path}") from None
    if not isinstance(data, dict):
        raise ConfigFileError("설정 파일은 JSON 객체여야 합니다.")
    return data


def config_problems(config: Mapping[str, Any]) -> list[str]:
    """안전장치에 걸리는 이유 목록. 비어 있으면 통과다."""
    problems: list[str] = []

    if "column.exclude.list" in config:
        problems.append("column.exclude.list는 쓰지 않습니다 (include.list만 씁니다).")

    include = config.get("column.include.list")
    if not isinstance(include, str) or not include.strip():
        problems.append("column.include.list가 없습니다.")
    else:
        prefix = f"{params.SOURCE_TABLE}."
        listed = [item.strip() for item in include.split(",")]
        if any(not item.startswith(prefix) for item in listed):
            problems.append(f"column.include.list의 항목은 모두 {prefix}<컬럼> 형태여야 합니다.")
        names = {item.removeprefix(prefix) for item in listed}
        expected = set(params.BRONZE_COLUMNS)
        if len(listed) != len(names):
            problems.append("column.include.list에 중복 항목이 있습니다.")
        if names != expected:
            extra, missing = sorted(names - expected), sorted(expected - names)
            problems.append(
                f"column.include.list가 Bronze 컬럼 10개와 다릅니다 (더 있음: {extra}, 모자람: {missing})."
            )

    if config.get("table.include.list") != params.SOURCE_TABLE:
        problems.append(f"table.include.list는 {params.SOURCE_TABLE} 하나여야 합니다.")

    password = config.get("database.password")
    if not isinstance(password, str) or not _PASSWORD_REFERENCE.fullmatch(password):
        problems.append("database.password는 ${env:이름} 형태여야 합니다 (평문 금지).")

    return problems


def check_connector_config(config: Mapping[str, Any]) -> None:
    problems = config_problems(config)
    if problems:
        raise ConfigFileError("\n".join(f"- {p}" for p in problems))


# --- REST 클라이언트 ---


def _urllib_transport(method: str, url: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=params.HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except ValueError:
            return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ConnectError(
            f"Kafka Connect에 닿지 않습니다: {urllib.parse.urlsplit(url).netloc}"
        ) from None


class ConnectClient:
    def __init__(self, base_url: str, transport: Transport = _urllib_transport) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def _call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> tuple[int, Any]:
        return self._transport(method, f"{self.base_url}{path}", body)

    def _ok(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        status, payload = self._call(method, path, body)
        if status >= 400:
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("message", ""))[:_MAX_ERROR_TEXT]
            raise ConnectError(f"{method} {path} 실패 (HTTP {status}) {detail}".strip())
        return payload

    def ping(self) -> None:
        self._ok("GET", "/")

    def plugin_classes(self) -> set[str]:
        """Connect에 올라와 있는 커넥터 플러그인의 클래스 이름 집합."""
        return {str(p.get("class", "")) for p in self._ok("GET", "/connector-plugins") or []}

    def list_connectors(self) -> list[str]:
        return list(self._ok("GET", "/connectors") or [])

    def exists(self, name: str) -> bool:
        status, _ = self._call("GET", f"/connectors/{name}/status")
        return status != 404

    def status(self, name: str) -> dict[str, Any]:
        return dict(self._ok("GET", f"/connectors/{name}/status"))

    def status_or_none(self, name: str) -> dict[str, Any] | None:
        """커넥터가 없거나 아직 상태를 못 주면 None."""
        code, payload = self._call("GET", f"/connectors/{name}/status")
        return payload if code < 400 and isinstance(payload, dict) else None

    def get_config(self, name: str) -> dict[str, str]:
        return dict(self._ok("GET", f"/connectors/{name}/config"))

    def create(self, config: Mapping[str, str]) -> None:
        body = {"name": config["name"], "config": {k: v for k, v in config.items() if k != "name"}}
        self._ok("POST", "/connectors", body)

    def stop(self, name: str) -> None:
        self._ok("PUT", f"/connectors/{name}/stop")

    def delete_offsets(self, name: str) -> None:
        self._ok("DELETE", f"/connectors/{name}/offsets")

    def delete(self, name: str) -> None:
        self._ok("DELETE", f"/connectors/{name}")


def states(status: Mapping[str, Any]) -> tuple[str, list[str]]:
    """(커넥터 상태, task 상태 목록)."""
    connector = str(status.get("connector", {}).get("state", "UNKNOWN"))
    tasks = [str(task.get("state", "UNKNOWN")) for task in status.get("tasks", [])]
    return connector, tasks


def is_running(status: Mapping[str, Any]) -> bool:
    connector, tasks = states(status)
    return connector == "RUNNING" and bool(tasks) and all(t == "RUNNING" for t in tasks)


def wait_running(
    client: ConnectClient,
    name: str,
    timeout: float = params.SETUP_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """커넥터와 task가 모두 RUNNING이 될 때까지 기다린다. 시간이 지나면 마지막 상태를 돌려준다."""
    deadline = clock() + timeout
    last: dict[str, Any] = {}
    while True:
        current = client.status_or_none(name)
        if current is not None:
            last = current
            connector, tasks = states(last)
            if is_running(last) or connector == "FAILED" or "FAILED" in tasks:
                return last
        if clock() >= deadline:
            return last
        sleep(1)
