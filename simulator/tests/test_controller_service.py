from datetime import UTC, datetime, timedelta

import pytest

from sim.common.control import ControlState
from sim.controller.control_writer import MemoryControlWriter
from sim.controller.log import IncidentLogError, MemoryIncidentLog
from sim.controller.pollution import MemoryPollution
from sim.controller.service import (
    ApplyError,
    ControllerService,
    IncidentActiveError,
    InvalidRequestError,
    UnavailableError,
)

T0 = datetime(2026, 10, 18, 8, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class Events:
    """기록기와 제어 파일 쓰기가 같은 목록에 순서대로 남긴다."""

    def __init__(self) -> None:
        self.items: list[tuple] = []


class OrderedLog(MemoryIncidentLog):
    def __init__(self, events: Events) -> None:
        super().__init__()
        self.events = events

    def write(self, record: dict) -> None:
        super().write(record)
        self.events.items.append(("log", record["phase"], record["type"]))


class OrderedWriter(MemoryControlWriter):
    def __init__(self, events: Events) -> None:
        super().__init__()
        self.events = events

    def write(self, running, mode, pg_extra_fail) -> None:
        super().write(running, mode, pg_extra_fail)
        self.events.items.append(("control", mode, running, dict(pg_extra_fail)))


def make(pollution=None, **kwargs):
    events = Events()
    log, writer, clock = OrderedLog(events), OrderedWriter(events), Clock()
    counter = iter(range(1, 10_000))
    service = ControllerService(
        writer,
        log,
        pollution if pollution is not None else MemoryPollution(),
        clock,
        lambda: f"00000000-0000-0000-0000-{next(counter):012d}",
        **kwargs,
    )
    service.start()
    events.items.clear()
    writer.writes.clear()
    return service, log, writer, clock, events


def test_start_record_comes_before_control_change() -> None:
    service, log, _, _, events = make()
    service.set_mode("burst")
    assert events.items == [("log", "start", "INGEST_LAG"), ("control", "burst", True, {})]
    record = log.records[0]
    assert record["at"] == "2026-10-18T08:00:00Z" and record["schema_version"] == 1
    assert record["params"] == {"mode": "burst", "planned_minutes": 15.0}


def test_start_record_failure_changes_nothing() -> None:
    service, log, writer, _, _ = make()
    log.fail_next = 1
    with pytest.raises(IncidentLogError):
        service.set_mode("burst")
    assert writer.writes == [] and service.mode == "normal" and service.active is None
    log.fail_next = 1
    pollution = service._pollution
    with pytest.raises(IncidentLogError):
        service.start_data_pollution("ORDER_TOTAL_MISMATCH", 5)
    assert pollution.applied == []  # DB도 그대로다


def test_apply_failure_leaves_failed_end_record() -> None:
    service, log, writer, _, _ = make()
    writer.fail_next = 1
    with pytest.raises(ApplyError):
        service.start_pg_outage("PG_B", 0.85, 10)
    assert [(r["phase"], r.get("ended_by")) for r in log.records] == [
        ("start", None),
        ("end", "failed"),
    ]
    assert service.pg_extra_fail == {} and service.active is None
    service, log, _, _, _ = make(MemoryPollution())
    service._pollution.fail_apply = True
    with pytest.raises(ApplyError):
        service.start_data_pollution("ORDER_TOTAL_MISMATCH", 5)
    assert log.records[-1]["ended_by"] == "failed"


def test_end_record_failure_is_retried_on_tick() -> None:
    service, log, writer, clock, _ = make()
    service.set_mode("burst")
    log.fail_next = 1
    service.set_mode("normal")
    assert writer.writes[-1] == ControlState(True, "normal", {})  # 되돌리기는 먼저 끝났다
    assert service.status()["pending_end_records"] == 1 and service.status()["last_error"]
    clock.advance(seconds=1)
    service.tick()
    assert service.status()["pending_end_records"] == 0 and service.status()["last_error"] is None
    assert [(r["phase"], r.get("ended_by")) for r in log.records] == [
        ("start", None),
        ("end", "manual"),
    ]


@pytest.mark.parametrize(
    ("mode", "minutes", "kind"), [("burst", 15, "INGEST_LAG"), ("medium", 60, "TRAFFIC_SURGE")]
)
def test_auto_return(mode: str, minutes: int, kind: str) -> None:
    service, log, writer, clock, _ = make()
    service.set_mode(mode)
    clock.advance(minutes=minutes, seconds=-1)
    service.tick()
    assert service.mode == mode
    clock.advance(seconds=1)
    service.tick()
    assert service.mode == "normal" and writer.writes[-1].mode == "normal"
    end = log.records[-1]
    assert (end["phase"], end["type"], end["ended_by"]) == ("end", kind, "timer")
    assert end["incident_id"] == log.records[0]["incident_id"]


def test_one_incident_at_a_time_except_pause() -> None:
    service, log, _, _, _ = make()
    service.set_mode("medium")
    with pytest.raises(IncidentActiveError):
        service.set_mode("burst")
    with pytest.raises(IncidentActiveError):
        service.start_pg_outage("PG_A")
    with pytest.raises(IncidentActiveError):
        service.start_data_pollution("ORDER_TOTAL_MISMATCH", 3)
    service.set_running(False)  # 일시정지는 예외
    assert service.running is False and service.pause is not None
    service.set_mode("normal")  # 모드 사건을 끝낸다
    assert service.active is None and service.mode == "normal"
    service.set_running(True)
    types = [(r["phase"], r["type"]) for r in log.records]
    assert types == [
        ("start", "TRAFFIC_SURGE"),
        ("start", "OPERATOR_PAUSE"),
        ("end", "TRAFFIC_SURGE"),
        ("end", "OPERATOR_PAUSE"),
    ]


def test_same_mode_is_no_change() -> None:
    service, log, writer, _, _ = make()
    service.set_mode("normal")
    service.set_running(True)
    assert log.records == [] and writer.writes == []


def test_pg_outage_sets_and_clears_control() -> None:
    service, log, writer, clock, _ = make()
    service.start_pg_outage("PG_B", 0.85, 10)
    assert writer.writes[-1] == ControlState(True, "normal", {"PG_B": 0.85})
    assert log.records[0]["params"] == {"pg": "PG_B", "extra_fail": 0.85, "planned_minutes": 10.0}
    clock.advance(minutes=3)
    service.end_active()
    assert writer.writes[-1] == ControlState(True, "normal", {})
    assert log.records[-1]["ended_by"] == "manual"
    with pytest.raises(InvalidRequestError):
        service.end_active()


@pytest.mark.parametrize(
    ("pg", "extra", "minutes"),
    [
        ("PG_C", 0.5, 10),
        ("PG_B", 0, 10),
        ("PG_B", 1.01, 10),
        ("PG_B", 0.5, 0),
        ("PG_B", 0.5, 61),
        ("PG_B", "0.5", 10),
        ("PG_B", True, 10),
    ],
)
def test_pg_outage_validation(pg, extra, minutes) -> None:
    service, log, writer, _, _ = make()
    with pytest.raises(InvalidRequestError):
        service.start_pg_outage(pg, extra, minutes)
    assert log.records == [] and writer.writes == []


def test_pollution_records_result() -> None:
    service, log, writer, _, _ = make(MemoryPollution(available=12))
    service.start_data_pollution("DUPLICATE_SUCCESS_PAYMENT", 20)
    start, end = log.records
    assert start["params"] == {
        "kind": "DUPLICATE_SUCCESS_PAYMENT",
        "requested_count": 20,
        "available_count": 12,
    }
    assert end["ended_by"] == "complete"
    assert end["result"]["affected_count"] == len(end["result"]["order_ids"]) == 12
    assert service.active is None and writer.writes == []  # 제어 파일은 건드리지 않는다


def test_pollution_without_target_fails_before_start_record() -> None:
    service, log, _, _, _ = make(MemoryPollution(available=0))
    with pytest.raises(InvalidRequestError):
        service.start_data_pollution("ORDER_TOTAL_MISMATCH", 5)
    assert log.records == []


@pytest.mark.parametrize(
    ("kind", "count"),
    [
        ("DROP", 5),
        ("ORDER_TOTAL_MISMATCH", 0),
        ("ORDER_TOTAL_MISMATCH", 501),
        ("ORDER_TOTAL_MISMATCH", 2.5),
    ],
)
def test_pollution_validation(kind, count) -> None:
    service, _, _, _, _ = make()
    with pytest.raises(InvalidRequestError):
        service.start_data_pollution(kind, count)


def test_pollution_unavailable_without_database() -> None:
    events = Events()
    service = ControllerService(
        OrderedWriter(events), OrderedLog(events), None, Clock(), lambda: "id"
    )
    with pytest.raises(UnavailableError):
        service.start_data_pollution("ORDER_TOTAL_MISMATCH", 5)


def test_shutdown_ends_everything_and_resets_control() -> None:
    service, log, writer, _, _ = make()
    service.start_pg_outage("PG_A", 0.9, 30)
    service.set_running(False)
    service.shutdown()
    ends = [(r["type"], r["ended_by"]) for r in log.records if r["phase"] == "end"]
    assert sorted(ends) == [("OPERATOR_PAUSE", "shutdown"), ("PG_OUTAGE", "shutdown")]
    assert writer.writes[-1] == ControlState(True, "normal", {})
    assert service.active is None and service.pause is None


def test_status_shows_type_and_times_only() -> None:
    service, _, _, _, _ = make()
    service.start_pg_outage("PG_B", 0.85, 10)
    status = service.status()
    assert status["active"] == {
        "type": "PG_OUTAGE",
        "started_at": "2026-10-18T08:00:00Z",
        "ends_at": "2026-10-18T08:10:00Z",
    }
    assert status["pg_extra_fail"] == {"PG_B": 0.85}


def test_records_have_no_pii() -> None:
    service, log, _, clock, _ = make()
    service.set_mode("burst")
    clock.advance(minutes=15)
    service.tick()
    service.start_data_pollution("ORDER_TOTAL_MISMATCH", 3)
    text = str(log.records)
    assert "example.com" not in text and "010-" not in text


def test_sink_pause_records_only_and_ends_manually() -> None:
    service, log, writer, clock, events = make()
    service.start_sink_pause("bronze-s3-sink-v2", 25)
    assert events.items == [("log", "start", "SINK_PAUSE")]  # 제어 파일은 건드리지 않는다
    assert log.records[0]["params"] == {"connector": "bronze-s3-sink-v2", "planned_minutes": 25.0}
    assert service.status()["active"]["ends_at"] is None
    with pytest.raises(IncidentActiveError):
        service.start_pg_outage("PG_A")
    clock.advance(minutes=90)
    service.tick()  # 자동 종료하지 않는다
    assert service.active is not None
    service.end_active()
    assert writer.writes == [] and service.active is None
    end = log.records[-1]
    assert (end["type"], end["ended_by"], end["at"]) == (
        "SINK_PAUSE",
        "manual",
        "2026-10-18T09:30:00Z",
    )


def test_sink_pause_start_record_failure_changes_nothing() -> None:
    service, log, _, _, _ = make()
    log.fail_next = 1
    with pytest.raises(IncidentLogError):
        service.start_sink_pause()
    assert service.active is None


def test_sink_pause_shutdown_writes_end() -> None:
    service, log, _, _, _ = make()
    service.start_sink_pause()
    service.shutdown()
    assert [(r["type"], r["ended_by"]) for r in log.records if r["phase"] == "end"] == [
        ("SINK_PAUSE", "shutdown")
    ]


@pytest.mark.parametrize(
    ("connector", "minutes"),
    [("bronze-s3-sink", 25), ("nope", 25), ("bronze-s3-sink-v2", 0), ("bronze-s3-sink-v2", 61)],
)
def test_sink_pause_validation(connector, minutes) -> None:
    service, log, _, _, _ = make()
    with pytest.raises(InvalidRequestError):
        service.start_sink_pause(connector, minutes)
    assert log.records == []
