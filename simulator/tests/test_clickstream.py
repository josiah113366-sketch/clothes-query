import json

import pytest
from typer.testing import CliRunner

import sim.clickstream.cli as clickstream_cli
from sim.cli import app
from sim.clickstream.topic import ClickMessage, TopicError, TopicInfo
from sim.clickstream.verify import verify

runner = CliRunner()
REMOTE = "kafka.example.internal:9093"


def record(event_id: str, session: str, time: str, event_type: str = "view") -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "member_id": "m-secret-1",
        "article_id": "0108775015",
        "event_time": f"2026-10-19T15:{time}+09:00",
        "session_id": session,
    }


def msg(partition: int, offset: int, value: dict | bytes | None, key: str | None = None):
    if isinstance(value, dict):
        key = value["session_id"] if key is None else key
        value = json.dumps(value).encode()
    return ClickMessage(partition, offset, None if key is None else key.encode(), value)


GOOD = [
    msg(0, 0, record("e1", "s1", "00:01")),
    msg(0, 1, record("e2", "s1", "00:02", "cart_add")),
    msg(1, 0, record("e3", "s2", "00:01")),
    msg(0, 2, record("e4", "s3", "00:00")),  # 다른 세션이라 시각이 앞서도 괜찮다
]


def failed(messages) -> dict[str, int]:
    report = verify(messages)
    return {name: r.failed for name, r in report.results.items() if r.failed}


def test_good_messages_pass() -> None:
    report = verify(GOOD)
    assert report.total == 4 and report.passed and not report.empty


def test_missing_field_or_bad_json() -> None:
    broken = record("e9", "s9", "00:01")
    del broken["article_id"]
    assert failed([*GOOD, msg(2, 0, broken), msg(2, 1, b"{not json", key="s9")]) == {"fields": 2}


def test_bad_event_type() -> None:
    assert failed([*GOOD, msg(2, 0, record("e9", "s9", "00:01", "purchase"))]) == {"event_type": 1}


def test_key_mismatch() -> None:
    assert failed([*GOOD, msg(2, 0, record("e9", "s9", "00:01"), key="other")]) == {"key": 1}


def test_session_in_two_partitions() -> None:
    assert failed([*GOOD, msg(2, 0, record("e9", "s1", "00:05"))]) == {"one_partition": 1}


def test_duplicate_event_id() -> None:
    assert failed([*GOOD, msg(2, 0, record("e1", "s9", "00:01"))]) == {"unique_event_id": 1}


def test_time_goes_backwards_in_session() -> None:
    assert failed([*GOOD, msg(0, 3, record("e9", "s1", "00:00"))]) == {"time_order": 1}


def test_empty_topic() -> None:
    report = verify([])
    assert report.empty and report.total == 0


def test_failure_locations_are_partition_offset_only() -> None:
    report = verify([*GOOD, msg(2, 7, record("e1", "s9", "00:01"))])
    assert report.results["unique_event_id"].locations == ["p2@7"]


# --- CLI ---


@pytest.fixture
def fake_kafka(monkeypatch):
    state = {"info": TopicInfo(3, "259200000"), "messages": GOOD, "calls": []}

    def describe(settings, topic):
        state["calls"].append("describe")
        return state["info"]

    monkeypatch.setattr(clickstream_cli.kafka_topic, "describe", describe)
    monkeypatch.setattr(
        clickstream_cli.kafka_topic,
        "create",
        lambda s, t, p: state["calls"].append(("create", t, p)),
    )
    monkeypatch.setattr(
        clickstream_cli.kafka_topic, "delete", lambda s, t: state["calls"].append(("delete", t))
    )
    monkeypatch.setattr(
        clickstream_cli.kafka_topic,
        "offsets",
        lambda s, t, p: {0: (0, 3), 1: (0, 1), 2: (0, 0)},
    )
    monkeypatch.setattr(
        clickstream_cli.kafka_topic, "read_all", lambda s, t, o: iter(state["messages"])
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "localhost:29092")
    return state


@pytest.mark.parametrize("args", [["setup"], ["reset", "--yes"]])
def test_remote_setup_and_reset_refused(monkeypatch, fake_kafka, args) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP", REMOTE)
    result = runner.invoke(app, ["clickstream", *args])
    assert result.exit_code == 1
    assert fake_kafka["calls"] == []  # 접속하지 않았다
    assert "example.internal" not in result.output


def test_reset_needs_yes(fake_kafka) -> None:
    result = runner.invoke(app, ["clickstream", "reset"])
    assert result.exit_code == 1
    assert fake_kafka["calls"] == []


def test_reset_deletes(fake_kafka) -> None:
    result = runner.invoke(app, ["clickstream", "reset", "--yes"])
    assert result.exit_code == 0
    assert ("delete", "clickstream") in fake_kafka["calls"]


def test_setup_creates_when_missing(fake_kafka) -> None:
    fake_kafka["info"] = None
    result = runner.invoke(app, ["clickstream", "setup"])
    assert result.exit_code == 0
    assert ("create", "clickstream", 3) in fake_kafka["calls"]


def test_setup_keeps_existing_and_warns_on_difference(fake_kafka) -> None:
    fake_kafka["info"] = TopicInfo(1, "604800000")
    result = runner.invoke(app, ["clickstream", "setup"])
    assert result.exit_code == 0
    assert "이미 있습니다" in result.output
    assert "파티션이 1개" in result.output and "retention.ms" in result.output
    assert not any(isinstance(c, tuple) for c in fake_kafka["calls"])


def test_status_shows_offsets(fake_kafka) -> None:
    result = runner.invoke(app, ["clickstream", "status"])
    assert result.exit_code == 0
    assert "파티션 0: low 0  high 3" in result.output
    assert "합계: 4건" in result.output


def test_status_missing_topic(fake_kafka) -> None:
    fake_kafka["info"] = None
    assert runner.invoke(app, ["clickstream", "status"]).exit_code == 1


def test_verify_passes(fake_kafka) -> None:
    result = runner.invoke(app, ["clickstream", "verify"])
    assert result.exit_code == 0
    assert result.output.count("통과") >= 6
    assert "m-secret-1" not in result.output


def test_verify_failure_exit_1_without_content(fake_kafka) -> None:
    fake_kafka["messages"] = [*GOOD, msg(2, 0, record("e9", "s1", "00:05"))]
    result = runner.invoke(app, ["clickstream", "verify"])
    assert result.exit_code == 1
    assert "p2@0" in result.output
    for secret in ("m-secret-1", "s1", "e9", "0108775015"):
        assert secret not in result.output.replace("p2@0", "")


def test_verify_empty_exit_2(fake_kafka) -> None:
    fake_kafka["messages"] = []
    result = runner.invoke(app, ["clickstream", "verify"])
    assert result.exit_code == 2
    assert "비어 있습니다" in result.output


def test_unreachable_kafka(monkeypatch, fake_kafka) -> None:
    def down(settings, topic):
        raise TopicError("Kafka에 닿지 않습니다.")

    monkeypatch.setattr(clickstream_cli.kafka_topic, "describe", down)
    for command in ("status", "verify", "setup"):
        result = runner.invoke(app, ["clickstream", command])
        assert result.exit_code == 1
        assert "닿지 않습니다" in result.output


def test_no_pii_in_any_output(fake_kafka) -> None:
    outputs = [runner.invoke(app, ["clickstream", c]).output for c in ("setup", "status", "verify")]
    for out in outputs:
        assert "example.com" not in out and "010-" not in out and "29092" not in out
