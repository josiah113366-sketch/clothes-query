import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from conftest import ORDER_ID, click, member_body, order_body, payment_body

from clothes_api.cursor import CHANGES_OVERLAP, ChangesCursor, decode_changes
from clothes_api.store import MemberChange

PII_VALUES = ("홍길동", "pii-user@example.com", "010-1234-5678", "1995-03-14")


def _no_pii(text: str) -> bool:
    return not any(v in text for v in PII_VALUES)


# --- 헬스 ---


def test_healthz_and_readyz(client, store, publisher):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    publisher.is_ready = False
    response = client.get("/readyz")
    assert response.status_code == 503 and response.json()["detail"] == "Kafka"
    publisher.is_ready = True
    store.down = True
    assert client.get("/readyz").json() == {"error": "NOT_READY", "detail": "DB"}


# --- 회원 ---


def test_member_created_then_idempotent_then_conflict(client):
    assert client.post("/v1/members", json=member_body()).status_code == 201
    assert client.post("/v1/members", json=member_body()).status_code == 200
    response = client.post("/v1/members", json=member_body(gender="M"))
    assert response.status_code == 409 and response.json()["error"] == "ID_CONFLICT"


def test_member_phone_taken(client):
    client.post("/v1/members", json=member_body())
    other = member_body(member_id="99999999-9999-4999-8999-999999999999", email="b@x.com")
    response = client.post("/v1/members", json=other)
    assert response.status_code == 409 and response.json()["error"] == "PHONE_TAKEN"


def test_validation_error_never_echoes_pii(client):
    response = client.post("/v1/members", json=member_body(gender="X", signup_at="2026-10-20"))
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "VALIDATION_ERROR"
    assert "gender" in body["detail"] and "signup_at" in body["detail"]
    assert _no_pii(response.text)


def test_naive_datetime_rejected(client):
    response = client.post("/v1/members", json=member_body(signup_at="2026-10-20T06:20:01"))
    assert response.status_code == 422


def test_unknown_field_rejected(client):
    response = client.post("/v1/members", json=member_body(status="WITHDRAWN"))
    assert response.status_code == 422


def test_signup_count(client):
    client.post("/v1/members", json=member_body())
    assert client.get(
        "/v1/members/signup-count", params={"from": "2026-10-20T00:00:00Z"}
    ).json() == {"count": 1}
    assert client.get(
        "/v1/members/signup-count", params={"from": "2026-10-21T00:00:00+09:00"}
    ).json() == {"count": 0}
    assert client.get("/v1/members/signup-count", params={"from": "2026-10-20"}).status_code == 422


def test_active_members_first_page_gives_changes_cursor(client):
    client.post("/v1/members", json=member_body())
    body = client.get("/v1/members/active").json()
    assert body["items"] == [member_body()["member_id"]]
    assert body["next_cursor"] is None
    assert decode_changes(body["changes_cursor"]).created_at <= datetime.now(UTC)


def test_member_changes_overlap_and_cursor(client, store):
    t0 = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
    ids = [UUID(int=i + 1) for i in range(3)]
    store.changes = [MemberChange(ids[i], t0 + timedelta(seconds=5 * i)) for i in range(3)]
    after = ChangesCursor(t0 + timedelta(seconds=15)).encode()
    body = client.get("/v1/members/changes", params={"after": after}).json()
    # 커서보다 10초 앞(5초)부터 겹쳐 돌려준다
    assert body["added"] == [str(ids[1]), str(ids[2])]
    assert body["removed"] == [] and body["has_more"] is False
    assert decode_changes(body["next_cursor"]).created_at == t0 + timedelta(seconds=15)
    assert CHANGES_OVERLAP == timedelta(seconds=10)


def test_member_changes_bad_cursor(client):
    response = client.get("/v1/members/changes", params={"after": "!!!"})
    assert response.status_code == 422 and response.json()["error"] == "BAD_CURSOR"


def test_catalog_pages(client, store):
    store.catalog_rows = [("0001", 100), ("0002", 200)]
    body = client.get("/v1/catalog").json()
    assert body == {
        "items": [{"article_id": "0001", "price": 100}, {"article_id": "0002", "price": 200}],
        "next_cursor": None,
    }


# --- 주문 ---


def _member(client):
    assert client.post("/v1/members", json=member_body()).status_code == 201


def test_order_created_idempotent_conflict(client):
    _member(client)
    assert client.post("/v1/orders", json=order_body()).status_code == 201
    assert client.post("/v1/orders", json=order_body()).status_code == 200
    changed = order_body(session_id="33333333-3333-4333-8333-333333333334")
    assert client.post("/v1/orders", json=changed).json()["error"] == "ID_CONFLICT"


def test_order_total_must_match_items(client):
    _member(client)
    response = client.post("/v1/orders", json=order_body(total_amount=100))
    assert response.status_code == 422


def test_order_duplicate_article_rejected(client):
    _member(client)
    item = order_body()["items"][0]
    second = {**item, "order_item_id": "44444444-4444-4444-8444-444444444445"}
    body = order_body(items=[item, second], total_amount=31600)
    assert client.post("/v1/orders", json=body).status_code == 422


def test_order_member_not_active(client, store):
    _member(client)
    store.inactive.add(UUID(member_body()["member_id"]))
    response = client.post("/v1/orders", json=order_body())
    assert response.status_code == 409 and response.json()["error"] == "MEMBER_NOT_ACTIVE"


def test_payment_rules(client):
    _member(client)
    client.post("/v1/orders", json=order_body())
    url = f"/v1/orders/{ORDER_ID}/payments"
    assert client.post(url, json=payment_body()).status_code == 201
    assert client.post(url, json=payment_body()).status_code == 200
    bad_pair = payment_body(payment_id="55555555-5555-4555-8555-555555555556", status="FAILED")
    assert client.post(url, json=bad_pair).status_code == 422
    backwards = payment_body(completed_at="2026-10-20T06:21:00Z")
    assert client.post(url, json=backwards).status_code == 422
    missing = "/v1/orders/00000000-0000-4000-8000-00000000ffff/payments"
    assert client.post(missing, json=payment_body()).status_code == 404


def test_status_transitions(client):
    _member(client)
    client.post("/v1/orders", json=order_body())
    url = f"/v1/orders/{ORDER_ID}"
    paid = {"status": "PAID", "updated_at": "2026-10-20T06:21:23Z"}
    assert client.patch(url, json=paid).status_code == 200
    assert client.patch(url, json=paid).status_code == 200  # 재시도
    refunded = {
        "status": "REFUNDED",
        "status_reason": "RETURN",
        "updated_at": "2026-10-21T00:00:00Z",
    }
    response = client.patch(url, json=refunded)
    assert response.status_code == 409 and response.json()["error"] == "INVALID_TRANSITION"
    wrong_reason = {"status": "CANCELLED", "updated_at": "2026-10-20T07:00:00Z"}
    assert client.patch(url, json=wrong_reason).status_code == 422


# --- 클릭 ---


def test_clicks_published_with_utc(client, publisher):
    response = client.post("/v1/events/clicks", json={"events": [click(), click(event_id="e-2")]})
    assert response.status_code == 202 and response.json() == {"accepted": 2, "failed": 0}
    record = publisher.events[0].record()
    assert record["event_time"] == "2026-10-20T06:20:05Z"
    assert set(record) == {
        "event_id", "event_type", "member_id", "article_id", "event_time", "session_id",
    }  # fmt: skip


def test_clicks_limit_and_failures(client, publisher):
    too_many = {"events": [click(event_id=f"e-{i}") for i in range(501)]}
    response = client.post("/v1/events/clicks", json=too_many)
    assert response.status_code == 413 and response.json()["error"] == "TOO_MANY_EVENTS"
    publisher.fail_after = 1
    body = client.post("/v1/events/clicks", json={"events": [click(), click(event_id="e-2")]})
    assert body.json() == {"accepted": 1, "failed": 1}
    bad = click(event_type="purchase")
    assert client.post("/v1/events/clicks", json={"events": [bad]}).status_code == 422


# --- 지표·로그 ---


def test_metrics_and_access_log_have_no_pii(client, caplog):
    logger = logging.getLogger("clothes_api.access")
    logger.propagate = True
    try:
        with caplog.at_level(logging.INFO, logger="clothes_api.access"):
            client.post("/v1/members", json=member_body())
            client.post("/v1/members", json=member_body(gender="X"))
    finally:
        logger.propagate = False
    lines = [json.loads(r.getMessage()) for r in caplog.records]
    assert {line["route"] for line in lines} == {"/v1/members"}
    assert {line["status"] for line in lines} == {201, 422}
    assert all(_no_pii(r.getMessage()) for r in caplog.records)
    text = client.get("/metrics").text
    assert 'api_requests_total{method="POST",route="/v1/members",status="201"}' in text
    assert 'api_errors_total{code="VALIDATION_ERROR"}' in text
    assert "api_members_total 1.0" in text
    assert _no_pii(text)


def test_order_route_label_is_template(client):
    _member(client)
    client.post("/v1/orders", json=order_body())
    client.patch(
        f"/v1/orders/{ORDER_ID}", json={"status": "PAID", "updated_at": "2026-10-20T07:00:00Z"}
    )
    text = client.get("/metrics").text
    assert 'route="/v1/orders/{order_id}"' in text and ORDER_ID not in text
