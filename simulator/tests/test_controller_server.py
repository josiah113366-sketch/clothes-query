import http.client
import json
from datetime import UTC, datetime

import pytest

from sim.controller.control_writer import MemoryControlWriter
from sim.controller.log import MemoryIncidentLog
from sim.controller.pollution import MemoryPollution
from sim.controller.server import ControllerServer, ServerConfigError, check_bind
from sim.controller.service import ControllerService

TOKEN = "test-token-abc123"


def _service(log=None):
    counter = iter(range(1, 10_000))
    return ControllerService(
        MemoryControlWriter(),
        log or MemoryIncidentLog(),
        MemoryPollution(),
        lambda: datetime(2026, 10, 18, 8, 0, 0, tzinfo=UTC),
        lambda: f"id-{next(counter)}",
    )


@pytest.fixture
def server():
    srv = ControllerServer(_service(), "127.0.0.1", 0, TOKEN)
    srv.start()
    yield srv
    srv.stop()


def call(srv, method, path, body=None, token=TOKEN):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    try:
        return res.status, json.loads(raw)
    except json.JSONDecodeError:
        return res.status, raw.decode()


def test_page_and_healthz_without_token(server) -> None:
    status, body = call(server, "GET", "/", token=None)
    assert status == 200 and "<button" in body and "cdn" not in body.lower()
    assert call(server, "GET", "/healthz", token=None) == (200, {"ok": True})


def test_token_required(server) -> None:
    assert call(server, "GET", "/api/status", token=None)[0] == 401
    assert call(server, "POST", "/api/mode", {"mode": "burst"}, token="wrong")[0] == 401
    assert server.service.mode == "normal"


def test_normal_flow_and_errors(server) -> None:
    status, body = call(server, "POST", "/api/mode", {"mode": "burst"})
    assert status == 200 and body["mode"] == "burst" and body["active"]["type"] == "INGEST_LAG"
    assert call(server, "POST", "/api/incidents/pg-outage", {"pg": "PG_B"})[0] == 409
    assert call(server, "POST", "/api/mode", {"mode": "normal"})[0] == 200
    status, body = call(server, "POST", "/api/incidents/pg-outage", {"pg": "PG_B", "minutes": 5})
    assert status == 200 and body["pg_extra_fail"] == {"PG_B": 0.85}
    status, body = call(server, "POST", "/api/incidents/end", {})
    assert status == 200 and body["pg_extra_fail"] == {}
    assert call(server, "POST", "/api/incidents/pg-outage", {"pg": "PG_Z"})[0] == 400
    assert call(server, "POST", "/api/mode", {"mode": "surge"})[0] == 400
    assert call(server, "POST", "/api/running", {"running": "no"})[0] == 400
    assert call(server, "POST", "/api/nope", {})[0] == 404
    status, body = call(
        server,
        "POST",
        "/api/incidents/data-pollution",
        {"kind": "ORDER_TOTAL_MISMATCH", "count": 3},
    )
    assert status == 200 and "result" not in json.dumps(body)  # 정답표 내용은 싣지 않는다


def test_bad_json_is_400(server) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request(
        "POST", "/api/mode", body=b"{not json", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert conn.getresponse().status == 400
    conn.close()


def test_log_failure_is_503_and_changes_nothing() -> None:
    log = MemoryIncidentLog()
    srv = ControllerServer(_service(log), "127.0.0.1", 0, TOKEN)
    srv.start()
    try:
        log.fail_next = 1
        status, body = call(srv, "POST", "/api/mode", {"mode": "burst"})
        assert status == 503 and srv.service.mode == "normal"
        assert TOKEN not in json.dumps(body)
    finally:
        srv.stop()


def test_no_token_needed_on_local_bind() -> None:
    srv = ControllerServer(_service(), "127.0.0.1", 0, None)
    srv.start()
    try:
        assert call(srv, "GET", "/api/status", token=None)[0] == 200
    finally:
        srv.stop()


def test_non_local_bind_without_token_is_refused() -> None:
    with pytest.raises(ServerConfigError) as info:
        check_bind("0.0.0.0", None)
    assert "SIM_CONTROLLER_TOKEN" in str(info.value)
    check_bind("0.0.0.0", TOKEN)
    check_bind("127.0.0.1", None)


def test_stop_ends_active_incident() -> None:
    log = MemoryIncidentLog()
    srv = ControllerServer(_service(log), "127.0.0.1", 0, TOKEN)
    srv.start()
    call(srv, "POST", "/api/incidents/pg-outage", {"pg": "PG_A"})
    srv.stop()
    assert log.records[-1]["ended_by"] == "shutdown"
    assert srv.service.pg_extra_fail == {}
