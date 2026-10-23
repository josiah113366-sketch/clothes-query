"""트래픽 보기. 시뮬레이터가 보낸 숫자(공유 폴더의 숫자 파일)와 API가 받은 숫자(/metrics)를 모은다.

TICK마다 한 번 표본을 만들어 최근 30분을 메모리에 둔다. 화면을 새로 열어도 같은 기록을 받는다.
속도(초당)는 화면이 이웃한 표본의 차이로 계산한다. API가 다시 시작해 카운터가 줄면 화면이 0으로 본다.
응답에 접속 주소, 토큰, 오류 원문을 싣지 않는다.
"""

import re
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sim.common.stats import STATS_SECONDS, read_stats

SAMPLE_SECONDS = STATS_SECONDS
HISTORY_SECONDS = 30 * 60
STALE_SECONDS = 15.0  # 숫자 파일이 이보다 오래되면 그 실행기는 멈춘 것으로 본다
METRICS_TIMEOUT_SECONDS = 1.5
HEALTH_ROUTES = frozenset({"/healthz", "/readyz", "/metrics"})

_LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)")
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')

Series = list[tuple[str, dict[str, str], float]]


def parse_prometheus(text: str) -> Series:
    """Prometheus 텍스트 형식 → (이름, 라벨, 값) 목록. 읽을 수 없는 줄은 건너뛴다."""
    series: Series = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            continue
        name, labels, raw = match.groups()
        try:
            value = float(raw)
        except ValueError:
            continue
        series.append((name, dict(_LABEL.findall(labels or "")), value))
    return series


def summarize_api(series: Series) -> dict[str, Any]:
    """화면에 필요한 값만 추린다. 상태 점검 경로(/healthz 등)의 요청은 빼고 센다."""
    out: dict[str, Any] = {
        "requests": 0.0,
        "status": {"2xx": 0.0, "4xx": 0.0, "5xx": 0.0},
        "latency_buckets": {},
        "orders": 0.0,
        "members": 0.0,
        "payments": {},
        "transitions": {},
        "kafka": {},
        "errors": {},
        "pool": {},
    }
    buckets: dict[str, float] = out["latency_buckets"]
    for name, labels, value in series:
        route = labels.get("route", "")
        if name == "api_requests_total" and route not in HEALTH_ROUTES:
            out["requests"] += value
            group = f"{labels.get('status', '')[:1]}xx"
            if group in out["status"]:
                out["status"][group] += value
        elif name == "api_request_seconds_bucket" and route not in HEALTH_ROUTES:
            le = labels.get("le", "")
            buckets[le] = buckets.get(le, 0.0) + value
        elif name == "api_orders_total":
            out["orders"] += value
        elif name == "api_members_total":
            out["members"] += value
        elif name == "api_payments_total":
            key = f"{labels.get('pg', '?')}:{labels.get('status', '?')}"
            out["payments"][key] = out["payments"].get(key, 0.0) + value
        elif name == "api_order_transitions_total":
            status = labels.get("status", "?")
            out["transitions"][status] = out["transitions"].get(status, 0.0) + value
        elif name == "api_kafka_produced_total":
            result = labels.get("result", "?")
            out["kafka"][result] = out["kafka"].get(result, 0.0) + value
        elif name == "api_errors_total":
            code = labels.get("code", "?")
            out["errors"][code] = out["errors"].get(code, 0.0) + value
        elif name in ("api_db_pool_size", "api_db_pool_available", "api_db_pool_waiting"):
            out["pool"][name.removeprefix("api_db_pool_")] = value
    return out


def http_fetcher(api_url: str, timeout: float = METRICS_TIMEOUT_SECONDS) -> Callable[[], str]:
    url = api_url.rstrip("/") + "/metrics"

    def fetch() -> str:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    return fetch


class TrafficMonitor:
    def __init__(
        self,
        stats_files: dict[str, Path],
        fetch_metrics: Callable[[], str] | None,
        now: Callable[[], float] = time.time,
        history_seconds: float = HISTORY_SECONDS,
    ) -> None:
        self.stats_files = stats_files
        self.fetch_metrics = fetch_metrics
        self._now = now
        self._samples: deque[dict[str, Any]] = deque(
            maxlen=max(1, int(history_seconds / SAMPLE_SECONDS))
        )
        self._lock = threading.Lock()

    def sample(self) -> dict[str, Any]:
        t = self._now()
        record: dict[str, Any] = {"t": round(t, 3), "sim": {}, "api": None}
        for name, path in self.stats_files.items():
            data = read_stats(path)
            fresh = data is not None and t - float(data.get("written_at", 0)) <= STALE_SECONDS
            record["sim"][name] = data if fresh else None
        if self.fetch_metrics is not None:
            try:
                record["api"] = summarize_api(parse_prometheus(self.fetch_metrics()))
            except Exception:  # noqa: BLE001  연결 실패·시간 초과는 "API 연결 안 됨"으로만 보인다
                record["api"] = None
        with self._lock:
            self._samples.append(record)
        return record

    def history(self, since: float | None = None) -> dict[str, Any]:
        with self._lock:
            samples = [s for s in self._samples if since is None or s["t"] > since]
        return {
            "sample_seconds": SAMPLE_SECONDS,
            "api_configured": self.fetch_metrics is not None,
            "samples": samples,
        }
