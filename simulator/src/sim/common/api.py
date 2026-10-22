"""업무 API(WAS) 클라이언트. 표준 라이브러리(urllib)만 쓴다.

behavior와 member가 서로 import하지 않고 이 모듈을 함께 쓴다. 주소(SIM_API_URL)는 호스트만 출력하고,
요청·응답 본문(가입 요청에는 PII가 있다)은 출력·예외 메시지에 싣지 않는다.

오류는 셋으로 나눈다.
- StoreUnavailable: 연결 실패·시간 초과·5xx·503. 실행기가 기다렸다 다시 시도한다(ID가 고정이라 중복 없음)
- StoreRejected: 4xx(검증 실패, ID 충돌 등). 다시 보내도 같은 결과다
- MemberNotActive: 주문한 회원이 ACTIVE가 아니다(409). 실행기가 그 회원을 목록에서 뺀다
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

from sim.common.config import ConfigError

API_URL_ENV = "SIM_API_URL"
BACKEND_ENV = "SIM_BACKEND"
BACKENDS = ("db", "api")
DEFAULT_TIMEOUT_SECONDS = 10.0


class StoreUnavailable(RuntimeError):
    """API에 닿지 않거나 일시 오류. 메시지에 본문을 담지 않는다."""


class StoreRejected(RuntimeError):
    """API가 요청을 거절했다(4xx). code는 API 오류 코드(예: ID_CONFLICT)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"API가 거절했습니다: {status} {code}")
        self.status = status
        self.code = code


class MemberNotActive(StoreRejected):
    pass


class PhoneTaken(StoreRejected):
    pass


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("시각은 시간대 정보가 있어야 합니다.")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"JSON으로 바꿀 수 없는 값: {type(value).__name__}")


def dumps(body: object) -> bytes:
    return json.dumps(
        body, default=_json_default, separators=(",", ":"), ensure_ascii=False
    ).encode()


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any


class ApiClient:
    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ConfigError(f"{API_URL_ENV}는 http(s)://호스트[:포트] 형식이어야 합니다.")
        self._base = base_url.rstrip("/")
        self._host = parts.hostname or ""
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"ApiClient(host={self._host!r})"

    @property
    def host(self) -> str:
        return self._host

    def request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        query: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        url = self._base + path
        if query:
            url += "?" + urlencode(query)
        data = dumps(body) if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                return ApiResponse(response.status, _read_json(response.read()))
        except urllib.error.HTTPError as error:
            status = error.code
            payload = _read_json(error.read())
            code = payload.get("error", "") if isinstance(payload, dict) else ""
            if status >= 500 or status == 429:
                raise StoreUnavailable(f"API 일시 오류: {status} {code}".strip()) from None
            if code == "MEMBER_NOT_ACTIVE":
                raise MemberNotActive(status, code) from None
            if code == "PHONE_TAKEN":
                raise PhoneTaken(status, code) from None
            raise StoreRejected(status, code or "UNKNOWN") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            reason = type(getattr(error, "reason", error)).__name__
            raise StoreUnavailable(f"API에 닿지 않습니다 ({reason})") from None

    def get(self, path: str, query: Mapping[str, str] | None = None) -> Any:
        return self.request("GET", path, query=query).body

    def health(self) -> None:
        """살아 있는지만 본다(/healthz). 실패하면 StoreUnavailable."""
        self.request("GET", "/healthz")


def _read_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def load_backend(env: Mapping[str, str] | None = None, backend: str | None = None) -> str:
    env = os.environ if env is None else env
    value = (backend or env.get(BACKEND_ENV, "") or "db").strip().lower()
    if value not in BACKENDS:
        raise ConfigError(
            f"--backend(또는 {BACKEND_ENV})는 {', '.join(BACKENDS)} 중 하나여야 합니다."
        )
    return value


def load_api_client(env: Mapping[str, str] | None = None) -> ApiClient:
    env = os.environ if env is None else env
    url = env.get(API_URL_ENV, "").strip()
    if not url:
        raise ConfigError(
            f"--backend api에는 {API_URL_ENV}가 필요합니다 (예: http://localhost:8000)."
        )
    return ApiClient(url)
