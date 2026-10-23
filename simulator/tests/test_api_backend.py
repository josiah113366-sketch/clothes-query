"""--backend api: API 클라이언트·Store·Sink·Source와 실행기의 API 오류 처리 (실제 API 없이).

가짜 API 서버는 표준 라이브러리 http.server로 같은 프로세스에서 띄운다.
"""

import json
import threading
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from behavior_fixtures import StaticMembers
from test_behavior_runner import MONDAY, make

from sim.behavior.api_sink import (
    CLICK_BATCH_MAX,
    ApiCatalogSource,
    ApiClickSink,
    ApiMemberSource,
    ApiOrderSink,
)
from sim.behavior.model import ClickEvent, NewPayment
from sim.behavior.runner import BehaviorError
from sim.behavior.sink import MemoryOrderSink
from sim.common.api import (
    ApiClient,
    MemberNotActive,
    PhoneTaken,
    StoreRejected,
    StoreUnavailable,
    dumps,
    load_backend,
)
from sim.common.config import ConfigError
from sim.member.api_store import ApiStore


class FakeApi:
    """경로별로 (상태, 본문)을 돌려주고 받은 요청을 기록한다."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, object]] = []
        self.routes: dict[tuple[str, str], list[tuple[int, object]]] = {}

    def on(self, method: str, path: str, *responses: tuple[int, object]) -> None:
        self.routes[(method, path)] = list(responses)

    def respond(self, method: str, path: str, query: dict, body: object) -> tuple[int, object]:
        self.requests.append((method, path, query, body))
        queue = self.routes.get((method, path))
        if not queue:
            return 404, {"error": "NO_ROUTE"}
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def api():
    fake = FakeApi()

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            parts = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, payload = fake.respond(self.command, parts.path, query, body)
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PATCH = _handle

        def log_message(self, *args) -> None:  # 테스트 출력에 섞지 않는다
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.client = ApiClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=5)
    yield fake
    server.shutdown()


# --- 클라이언트 ---


def test_error_mapping(api):
    api.on("POST", "/x", (503, {"error": "DB_BUSY"}))
    with pytest.raises(StoreUnavailable):
        api.client.request("POST", "/x", {})
    api.on("POST", "/x", (409, {"error": "MEMBER_NOT_ACTIVE"}))
    with pytest.raises(MemberNotActive):
        api.client.request("POST", "/x", {})
    api.on("POST", "/x", (409, {"error": "PHONE_TAKEN"}))
    with pytest.raises(PhoneTaken):
        api.client.request("POST", "/x", {})
    api.on("POST", "/x", (422, {"error": "VALIDATION_ERROR"}))
    with pytest.raises(StoreRejected) as info:
        api.client.request("POST", "/x", {})
    assert info.value.code == "VALIDATION_ERROR" and not isinstance(info.value, MemberNotActive)


def test_unreachable_is_unavailable():
    client = ApiClient("http://127.0.0.1:9", timeout=1)
    with pytest.raises(StoreUnavailable) as info:
        client.health()
    assert "127.0.0.1" not in str(info.value)


def test_dumps_utc_and_rejects_naive():
    raw = dumps({"t": datetime(2026, 10, 20, 15, 0, tzinfo=UTC), "d": date(1990, 1, 2)})
    assert raw == b'{"t":"2026-10-20T15:00:00Z","d":"1990-01-02"}'
    with pytest.raises(ValueError):
        dumps({"t": datetime(2026, 10, 20)})


def test_client_repr_and_url_check():
    assert "secret" not in repr(ApiClient("http://api.internal:8000"))
    with pytest.raises(ConfigError):
        ApiClient("api.internal:8000")
    assert load_backend({}, None) == "db" and load_backend({"SIM_BACKEND": "API"}) == "api"
    with pytest.raises(ConfigError):
        load_backend({}, "kafka")


# --- 회원 ---


def test_member_store(api):
    from pathlib import Path

    from sim.common.regions import load_regions
    from sim.common.rng import SimRandom
    from sim.member.generate import draw_phone, generate_member

    regions = load_regions(Path(__file__).resolve().parents[1] / "data/region_weights_202609.csv")
    rng = SimRandom(1)
    member = generate_member(rng, datetime(2026, 10, 20, tzinfo=UTC), regions, draw_phone(rng))
    api.on("GET", "/healthz", (200, {"status": "ok"}))
    api.on("GET", "/v1/members/signup-count", (200, {"count": 7}))
    api.on("POST", "/v1/members", (201, {}), (200, {}))
    store = ApiStore(api.client)
    store.connect()
    assert store.count_since(datetime(2026, 10, 1, tzinfo=UTC)) == 7
    store.insert(member)
    store.insert(member)
    query = api.requests[1][2]
    assert query == {"from": "2026-10-01T00:00:00+00:00"}
    sent = api.requests[2][3]
    assert "status" not in sent and "withdrawn_at" not in sent
    assert sent["signup_at"] == "2026-10-20T00:00:00Z"


# --- 주문 ---


def _payment() -> NewPayment:
    t = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
    return NewPayment("p-1", "o-1", 1, "CARD", "PG_A", 100, "FAILED", "PG_TIMEOUT", t, t)


def test_order_sink_payloads(api):
    api.on("POST", "/v1/orders/o-1/payments", (201, {}))
    api.on("PATCH", "/v1/orders/o-1", (200, {}))
    sink = ApiOrderSink(api.client)
    sink.add_payment(_payment())
    sink.update_order_status("o-1", "CANCELLED", "USER_REQUEST", datetime(2026, 10, 20, tzinfo=UTC))
    payment = api.requests[0][3]
    assert "order_id" not in payment and payment["failure_code"] == "PG_TIMEOUT"
    assert api.requests[1][3] == {
        "status": "CANCELLED",
        "status_reason": "USER_REQUEST",
        "updated_at": "2026-10-20T00:00:00Z",
    }


# --- 클릭 ---


def _click(i: int) -> ClickEvent:
    return ClickEvent(f"e-{i}", "view", "m", "a", datetime(2026, 10, 20, tzinfo=UTC), "s")


def test_click_sink_batches_and_counts(api):
    api.on("POST", "/v1/events/clicks", (202, {"accepted": CLICK_BATCH_MAX, "failed": 0}))
    sink = ApiClickSink(api.client, start_timer=False)
    for i in range(CLICK_BATCH_MAX):
        sink.publish(_click(i))
    assert len(api.requests) == 1  # 500건이 차면 바로 보낸다
    assert len(api.requests[0][3]["events"]) == CLICK_BATCH_MAX
    api.on("POST", "/v1/events/clicks", (503, {"error": "X"}))
    warnings: list[str] = []
    sink._warn = warnings.append
    sink.publish(_click(9999))
    sink.close()
    assert sink.stats.sent == CLICK_BATCH_MAX and sink.stats.failed == 1
    assert len(warnings) == 1


def test_click_sink_timer_flushes(api):
    api.on("POST", "/v1/events/clicks", (202, {"accepted": 1, "failed": 0}))
    sink = ApiClickSink(api.client, flush_seconds=0.05)
    sink.publish(_click(1))
    for _ in range(100):
        if api.requests:
            break
        threading.Event().wait(0.02)
    sink.close()
    assert sink.stats.sent == 1


# --- 목록 ---


def test_member_source_full_then_changes(api):
    api.on(
        "GET",
        "/v1/members/active",
        (200, {"items": ["b", "a"], "next_cursor": "c1", "changes_cursor": "k0"}),
        (200, {"items": ["c"], "next_cursor": None}),
    )
    api.on(
        "GET",
        "/v1/members/changes",
        (200, {"added": ["a", "d"], "removed": [], "next_cursor": "k1", "has_more": True}),
        (200, {"added": ["e"], "removed": ["b"], "next_cursor": "k2", "has_more": False}),
    )
    source = ApiMemberSource(api.client)
    assert source.read_active_members() == ["a", "b", "c"]
    assert source.read_active_members() == ["a", "c", "d", "e"]  # 겹친 a는 한 번만
    assert [r[2] for r in api.requests if r[1] == "/v1/members/changes"] == [
        {"after": "k0"},
        {"after": "k1"},
    ]
    source.discard("a")
    api.on("GET", "/v1/members/changes", (200, {"added": [], "next_cursor": "k2"}))
    assert source.read_active_members() == ["c", "d", "e"]


def test_catalog_source_pages(api):
    api.on(
        "GET",
        "/v1/catalog",
        (200, {"items": [{"article_id": "1", "price": 10}], "next_cursor": "x"}),
        (200, {"items": [{"article_id": "2", "price": 20}], "next_cursor": None}),
    )
    catalog = ApiCatalogSource(api.client).read_catalog()
    assert catalog.article_ids == ("1", "2") and catalog.prices == (10, 20)


# --- 실행기 ---


class FlakyOrders(MemoryOrderSink):
    """처음 몇 번은 API가 닿지 않고, 지정한 회원의 주문은 비활성으로 거절한다."""

    def __init__(self, unavailable: int = 0, inactive: set[str] | None = None) -> None:
        super().__init__()
        self.unavailable = unavailable
        self.inactive = inactive or set()

    def create_order(self, order, items) -> None:
        if self.unavailable > 0:
            self.unavailable -= 1
            raise StoreUnavailable("API에 닿지 않습니다")
        if order.member_id in self.inactive:
            raise MemberNotActive(409, "MEMBER_NOT_ACTIVE")
        super().create_order(order, items)


def test_runner_retries_unavailable_and_drops_inactive(member_ids, catalog):
    orders = FlakyOrders(unavailable=2, inactive=set(member_ids[:200]))
    runner, orders, _, lines = make(
        member_ids[:200] + member_ids[200:400], catalog, orders=orders, visits_daily=200_000
    )
    summary = runner.run_until(MONDAY.replace(hour=2))
    assert summary.orders > 0 and summary.orders_rejected > 0
    assert any("API 연결 오류" in line for line in lines)
    created = {c[1].member_id for c in orders.calls if c[0] == "create_order"}
    assert not created & set(member_ids[:200])
    assert summary.reconnects >= 1


def test_runner_rejected_stops(member_ids, catalog):
    class Rejecting(MemoryOrderSink):
        def create_order(self, order, items) -> None:
            raise StoreRejected(422, "VALIDATION_ERROR")

    runner, *_ = make(member_ids, catalog, orders=Rejecting(), visits_daily=200_000)
    with pytest.raises(BehaviorError, match="VALIDATION_ERROR"):
        runner.run_until(MONDAY.replace(hour=2))


def test_pool_refresh_uses_source_interval(member_ids, catalog):
    class FastMembers(StaticMembers):
        refresh_seconds = 5.0

    runner, *_ = make(member_ids, catalog, visits_daily=1_000)
    runner.members = FastMembers(member_ids)
    runner.run_until(MONDAY.replace(hour=1))  # 실제 60초(배속 60)
    assert runner.members.reads >= 10


def test_member_pool_discard_keeps_last(member_ids):
    from sim.behavior.pool import MemberPool

    pool = MemberPool(42, member_ids[:2])
    assert pool.discard(member_ids[0]) and len(pool) == 1
    assert not pool.discard(member_ids[1]) and len(pool) == 1
