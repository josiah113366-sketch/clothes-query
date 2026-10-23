import json

from test_controller_server import TOKEN, _service, call

from sim.common.stats import StatsFile, read_stats, stats_path
from sim.controller.server import ControllerServer
from sim.controller.traffic import (
    SAMPLE_SECONDS,
    TrafficMonitor,
    parse_prometheus,
    summarize_api,
)

METRICS = """\
# HELP api_requests_total 요청 수
# TYPE api_requests_total counter
api_requests_total{route="/orders",method="POST",status="201"} 40.0
api_requests_total{route="/orders/{order_id}",method="PATCH",status="409"} 2.0
api_requests_total{route="/events/clicks",method="POST",status="503"} 1.0
api_requests_total{route="/metrics",method="GET",status="200"} 99.0
api_request_seconds_bucket{route="/orders",le="0.05"} 30.0
api_request_seconds_bucket{route="/orders",le="+Inf"} 40.0
api_request_seconds_bucket{route="/healthz",le="+Inf"} 7.0
api_orders_total 40.0
api_members_total 5.0
api_payments_total{status="SUCCESS",pg="PG_A"} 30.0
api_payments_total{status="FAILED",pg="PG_B"} 3.0
api_order_transitions_total{status="PAID"} 28.0
api_kafka_produced_total{result="ok"} 500.0
api_errors_total{code="DB_BUSY"} 1.0
api_db_pool_size 10.0
api_db_pool_available 7.0
api_db_pool_waiting 0.0
broken line here
api_orders_created 1.5e3
"""


def test_parse_prometheus_reads_labels_and_skips_junk() -> None:
    series = parse_prometheus(METRICS)
    assert ("api_orders_total", {}, 40.0) in series
    assert ("api_orders_created", {}, 1500.0) in series
    route = {"route": "/orders/{order_id}", "method": "PATCH", "status": "409"}
    assert ("api_requests_total", route, 2.0) in series
    assert all(name != "broken" for name, _, _ in series)


def test_summarize_api_excludes_health_routes() -> None:
    api = summarize_api(parse_prometheus(METRICS))
    assert api["requests"] == 43.0  # /metrics 99건은 빼고 센다
    assert api["status"] == {"2xx": 40.0, "4xx": 2.0, "5xx": 1.0}
    assert api["latency_buckets"] == {"0.05": 30.0, "+Inf": 40.0}
    assert api["payments"] == {"PG_A:SUCCESS": 30.0, "PG_B:FAILED": 3.0}
    assert api["orders"] == 40.0 and api["members"] == 5.0
    assert api["transitions"] == {"PAID": 28.0} and api["kafka"] == {"ok": 500.0}
    assert api["errors"] == {"DB_BUSY": 1.0}
    assert api["pool"] == {"size": 10.0, "available": 7.0, "waiting": 0.0}


def test_stats_file_round_trip_and_path(tmp_path) -> None:
    control = tmp_path / "control.json"
    path = stats_path(control, "behavior")
    assert path == tmp_path / "stats-behavior.json"
    StatsFile(path, now=lambda: 1000.0).write({"visits": 3, "mode": "normal"})
    assert read_stats(path) == {"written_at": 1000.0, "visits": 3, "mode": "normal"}
    assert not list(tmp_path.glob(".*.tmp"))  # 임시 파일이 남지 않는다
    path.write_text("{깨짐", encoding="utf-8")
    assert read_stats(path) is None
    assert read_stats(tmp_path / "없음.json") is None


def test_stats_file_failure_warns_once_and_continues(tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")  # 폴더 자리에 파일이 있어 쓰기가 실패한다
    warnings: list[str] = []
    stats = StatsFile(blocker / "stats-member.json", warn=warnings.append)
    stats.write({"signups": 1})
    stats.write({"signups": 2})
    assert len(warnings) == 1 and "계속" in warnings[0]


def test_monitor_marks_stale_files_and_api_failure(tmp_path) -> None:
    now = [1000.0]
    fresh, stale = tmp_path / "stats-behavior.json", tmp_path / "stats-member.json"
    StatsFile(fresh, now=lambda: 995.0).write({"visits": 10})
    StatsFile(stale, now=lambda: 900.0).write({"signups": 1})

    def down() -> str:
        raise OSError("연결 거부")

    monitor = TrafficMonitor({"behavior": fresh, "member": stale}, down, now=lambda: now[0])
    record = monitor.sample()
    assert record["sim"]["behavior"]["visits"] == 10
    assert record["sim"]["member"] is None  # 15초보다 오래된 숫자 파일
    assert record["api"] is None


def test_monitor_keeps_bounded_history_and_since(tmp_path) -> None:
    now = [0.0]
    monitor = TrafficMonitor({}, lambda: METRICS, now=lambda: now[0], history_seconds=10)
    for i in range(10):
        now[0] = i * SAMPLE_SECONDS
        monitor.sample()
    history = monitor.history()
    assert [s["t"] for s in history["samples"]] == [10.0, 12.0, 14.0, 16.0, 18.0]
    assert history["api_configured"] is True
    assert [s["t"] for s in monitor.history(since=14.0)["samples"]] == [16.0, 18.0]
    assert history["samples"][0]["api"]["orders"] == 40.0


def test_traffic_route_requires_token_and_filters(tmp_path) -> None:
    monitor = TrafficMonitor({}, None, now=lambda: 5.0)
    monitor.sample()
    srv = ControllerServer(_service(), "127.0.0.1", 0, TOKEN, monitor)
    srv.start()
    try:
        assert call(srv, "GET", "/api/traffic", token=None)[0] == 401
        status, body = call(srv, "GET", "/api/traffic")
        assert status == 200 and body["api_configured"] is False
        assert [s["t"] for s in body["samples"]][-1] >= 5.0
        status, body = call(srv, "GET", "/api/traffic?since=999999999999")
        assert status == 200 and body["samples"] == []
        status, body = call(srv, "GET", "/api/traffic?since=abc")  # 틀린 값은 전체
        assert status == 200 and body["samples"]
        assert TOKEN not in json.dumps(body)
    finally:
        srv.stop()


def test_traffic_route_without_monitor(tmp_path) -> None:
    srv = ControllerServer(_service(), "127.0.0.1", 0, TOKEN)
    srv.start()
    try:
        assert call(srv, "GET", "/api/traffic") == (
            200,
            {"samples": [], "api_configured": False},
        )
    finally:
        srv.stop()
