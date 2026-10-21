import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sim.behavior import sink
from sim.behavior.model import ClickEvent
from sim.common.db import DatabaseTargetError, check_db_target

EVENT = ClickEvent(
    "e-1", "view", "m-1", "0108775015", datetime(2026, 10, 12, 0, 30, 0, tzinfo=UTC), "s-1"
)


def test_jsonl_click_sink_writes_six_fields_in_utc(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "clicks.jsonl"
    click = sink.JsonlClickSink(path)
    click.publish(EVENT)
    click.publish(EVENT)
    click.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert set(record) == {
        "event_id",
        "event_type",
        "member_id",
        "article_id",
        "event_time",
        "session_id",
    }
    assert record["event_time"] == "2026-10-12T00:30:00Z"
    assert datetime.fromisoformat(record["event_time"]) == EVENT.event_time


def test_memory_and_null_sinks() -> None:
    memory = sink.MemoryClickSink()
    memory.publish(EVENT)
    assert memory.events == [EVENT]
    sink.NullClickSink().publish(EVENT)  # 아무것도 하지 않는다


def test_sql_uses_placeholders_only() -> None:
    for statement in (sink.ORDER_INSERT, sink.ITEM_INSERT, sink.PAYMENT_INSERT):
        text = statement.as_string(None)
        assert "%s" in text and "'" not in text
    assert "orders" in sink.ORDER_INSERT.as_string(None)
    assert '"order_items"' in sink.ITEM_INSERT.as_string(None)


def test_db_sink_without_connection_raises_operational_error() -> None:
    import psycopg

    db = sink.DbOrderSink("postgresql://u:pw@localhost:5432/x")
    with pytest.raises(psycopg.OperationalError):
        db.add_payment(None)  # type: ignore[arg-type]


SECRET_HOST = "prod-db.internal.example.net"
SECRET_PASSWORD = "s3cr3t-pw"


@pytest.mark.parametrize(
    "url", ["postgresql://u:pw@localhost:5432/clothes", "postgresql://u:pw@127.0.0.1/clothes"]
)
def test_check_db_target_allows_local(url: str) -> None:
    check_db_target(url, allow_remote=False)


def test_check_db_target_rejects_remote_without_switch() -> None:
    url = f"postgresql://u:{SECRET_PASSWORD}@{SECRET_HOST}:5432/clothes"
    with pytest.raises(DatabaseTargetError) as info:
        check_db_target(url, allow_remote=False)
    message = str(info.value)
    assert "SIM_ALLOW_REMOTE_DB=1" in message
    assert SECRET_HOST not in message and SECRET_PASSWORD not in message
    check_db_target(url, allow_remote=True)  # 명시적으로 허용하면 통과
