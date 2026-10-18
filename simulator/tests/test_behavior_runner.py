import math
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from behavior_fixtures import (
    Script,
    StaticCatalog,
    StaticMembers,
    consistency_problems,
    first_monday,
    replay,
)

from sim.behavior.runner import BehaviorError, BehaviorRunner
from sim.behavior.sink import MemoryClickSink, MemoryOrderSink
from sim.common import curve
from sim.common.clock import FakeTime, SimClock
from sim.common.control import ControlState, FileControlSource

MONDAY = first_monday()
NORMAL = ControlState(True, "normal")
BURST = ControlState(True, "burst")
MEDIUM = ControlState(True, "medium")
PAUSED = ControlState(False, "normal")


def make(member_ids, catalog, *, steps=None, speed=60.0, start=MONDAY, orders=None, **kwargs):
    clock = SimClock.fake(FakeTime(start), speed=speed)
    orders = orders or MemoryOrderSink()
    clicks = MemoryClickSink()
    lines: list[str] = []
    control = kwargs.pop("control", None) or Script(clock, steps or [(0, NORMAL)])
    kwargs.setdefault("seed", 42)
    kwargs.setdefault("run_salt", 1)
    runner = BehaviorRunner(
        orders,
        clicks,
        StaticMembers(member_ids),
        StaticCatalog(catalog),
        clock,
        control,
        out=lines.append,
        **kwargs,
    )
    return runner, orders, clicks, lines


def _within_5_sigma(count: int, expected: float) -> bool:
    return abs(count - expected) <= 5 * math.sqrt(expected)


def _expected_normal(daily: float, from_hour: int, to_hour: int) -> float:
    """월요일 from_hour~to_hour시의 normal 기대 방문 수 (곡선은 시간 단위 계단)."""
    hours = range(from_hour, to_hour)
    return sum(daily / 24 * curve.rate_factor("normal", MONDAY + timedelta(hours=h)) for h in hours)


def _visit_times(clicks: MemoryClickSink) -> list:
    first: dict[str, object] = {}
    for c in clicks.events:
        if c.event_type == "view" and c.session_id not in first:
            first[c.session_id] = c.event_time
    return sorted(first.values())


# --- 방문 속도와 모드 ---


@pytest.fixture(scope="module")
def week(member_ids, catalog):
    runner, orders, clicks, _ = make(member_ids, catalog, speed=3600.0, visits_daily=3_000)
    runner.run_until(MONDAY + timedelta(days=7))
    return runner, orders, clicks


def test_visit_rate_over_a_week(week) -> None:
    runner, _, _ = week
    assert _within_5_sigma(runner.summary.visits, 7 * 3_000)


def test_visit_hour_shares_follow_curve(week) -> None:
    _, _, clicks = week
    times = [t for t in _visit_times(clicks) if t < MONDAY + timedelta(days=7)]
    total = len(times)
    for start, end, share in curve.HOUR_SHARE:
        count = sum(1 for t in times if start <= t.hour < end)
        assert abs(count - total * share) <= 5 * math.sqrt(total * share * (1 - share))


@pytest.mark.parametrize(("state", "factor"), [(BURST, 18.0), (MEDIUM, 5.4)])
def test_fixed_modes_one_hour(member_ids, catalog, state, factor) -> None:
    runner, _, _, lines = make(
        member_ids, catalog, steps=[(0, state)], mode=state.mode, visits_daily=3_000
    )
    runner.run_until(MONDAY + timedelta(hours=1))
    assert _within_5_sigma(runner.summary.visits, 3_000 / 24 * factor)
    assert not any("→" in line for line in lines)


def test_mode_switch_segments(member_ids, catalog) -> None:
    # 배속 10: normal 3시간(밤 0~3시) → burst 1시간 → normal 3시간
    hours = 360  # 실제 초 = 시뮬레이터 1시간
    steps = [(0, NORMAL), (3 * hours, BURST), (4 * hours, NORMAL)]
    runner, _, clicks, lines = make(member_ids, catalog, steps=steps, speed=10, visits_daily=3_000)
    runner.run_until(MONDAY + timedelta(hours=7))
    times = _visit_times(clicks)
    seg = [
        sum(1 for t in times if MONDAY + timedelta(hours=a) <= t < MONDAY + timedelta(hours=b))
        for a, b in ((0, 3), (3, 4), (4, 7))
    ]
    assert _within_5_sigma(seg[0], _expected_normal(3_000, 0, 3))
    assert _within_5_sigma(seg[1], 3_000 * 18 / 24)
    assert _within_5_sigma(seg[2], _expected_normal(3_000, 4, 7))
    assert [line for line in lines if "→" in line] == [
        "mode: normal → burst",
        "mode: burst → normal",
    ]


def test_pause_stops_visits_but_not_queue(member_ids, catalog) -> None:
    hour = 60  # 배속 60: 실제 60초 = 시뮬레이터 1시간
    steps = [(0, BURST), (hour, PAUSED), (4 * hour, BURST)]
    runner, orders, _, _ = make(member_ids, catalog, steps=steps, visits_daily=3_000)
    runner.run_until(MONDAY + timedelta(hours=1, minutes=1))
    visits, updates = runner.summary.visits, len(orders.calls)
    runner.run_until(MONDAY + timedelta(hours=3, minutes=59))
    assert runner.summary.visits == visits  # 멈춘 동안 새 방문 없음
    assert len(orders.calls) > updates  # 큐의 결제·전이는 계속
    runner.run_until(MONDAY + timedelta(hours=5))
    assert runner.summary.visits > visits  # 다시 켜면 방문이 는다


# --- 끝까지 돌린 결과 ---


@pytest.fixture(scope="module")
def day(member_ids, catalog):
    runner, orders, clicks, lines = make(
        member_ids, catalog, steps=[(0, BURST)], mode="burst", speed=600.0, visits_daily=3_000
    )
    runner.run_until(MONDAY + timedelta(hours=8))  # burst: 시간당 2,250 방문, 약 800 주문
    runner.drain()
    return runner, orders, clicks, lines


def test_drain_empties_queue_and_rules_hold(day) -> None:
    runner, orders, clicks, _ = day
    assert len(runner.queue) == 0 and runner.summary.remaining_queue == 0
    state = replay(orders.calls)
    assert len(state) == runner.summary.orders > 500
    assert consistency_problems(state, clicks.events) == []


def test_final_status_distribution(day) -> None:
    _, orders, _, _ = day
    state = replay(orders.calls)
    n = len(state)
    final = Counter(s.status for s in state.values())
    expected = {
        "PAYMENT_FAILED": 0.985 * 0.0404,
        "CANCELLED": 0.015 + 0.985 * 0.9596 * 0.03,
        "REFUNDED": 0.985 * 0.9596 * 0.97 * 0.07,
        "DELIVERED": 0.985 * 0.9596 * 0.97 * 0.93,
    }
    for status, p in expected.items():
        assert abs(final[status] - n * p) <= 5 * math.sqrt(n * p * (1 - p)), status
    assert set(final) <= set(expected)


def test_summary_counts_match_sink(day) -> None:
    runner, orders, clicks, _ = day
    s = runner.summary
    assert s.orders == sum(1 for c in orders.calls if c[0] == "create_order")
    assert s.payments == sum(1 for c in orders.calls if c[0] == "add_payment")
    assert s.views + s.cart_adds == len(clicks.events)
    assert sum(s.transitions.values()) == sum(
        1 for c in orders.calls if c[0] == "update_order_status"
    )


def test_reproducible_with_same_seed_and_salt(member_ids, catalog) -> None:
    def once(salt: int):
        runner, orders, clicks, _ = make(
            member_ids, catalog, steps=[(0, BURST)], mode="burst", run_salt=salt, visits_daily=3_000
        )
        runner.run_until(MONDAY + timedelta(minutes=40))
        runner.drain()
        return orders.calls, clicks.events

    a, b, c = once(1), once(1), once(2)
    assert a == b
    ids = lambda calls: (
        {x[1].order_id for x in calls[0] if x[0] == "create_order"}
        | {e.session_id for e in calls[1]}
    )
    assert ids(a) and ids(a).isdisjoint(ids(c))


def test_pg_extra_fail_reaches_attempts(member_ids, catalog) -> None:
    runner, orders, _, _ = make(
        member_ids,
        catalog,
        steps=[(0, BURST)],
        mode="burst",
        visits_daily=3_000,
        pg_extra_fail={"PG_A": 1.0},
    )
    runner.run_until(MONDAY + timedelta(minutes=40))
    runner.drain()
    payments = [c[1] for c in orders.calls if c[0] == "add_payment"]
    pg_a = [p for p in payments if p.pg == "PG_A"]
    assert pg_a and all(p.failure_code in ("PG_TIMEOUT", "PG_ERROR") for p in pg_a)
    assert any(p.status == "SUCCESS" for p in payments if p.pg == "PG_B")


# --- 제어 파일 ---


def test_file_control_surge_keeps_last_state(member_ids, catalog, tmp_path: Path) -> None:
    path = tmp_path / "control.json"
    path.write_text('{"running": true, "mode": "burst"}')
    warnings: list[str] = []
    clock_holder = {}

    class SwitchingFile(FileControlSource):
        def read(self):
            if clock_holder["clock"].real_elapsed() >= 30:
                path.write_text('{"running": true, "mode": "surge"}')
            return super().read()

    source = SwitchingFile(path, warn=warnings.append)
    runner, _, _, lines = make(member_ids, catalog, control=source, visits_daily=3_000)
    clock_holder["clock"] = runner.clock
    runner.run_until(MONDAY + timedelta(hours=1))
    assert runner.mode == "burst"
    assert len(warnings) == 1
    assert [line for line in lines if "→" in line] == ["mode: normal → burst"]


# --- 재연결, 23505, 종료 ---


class FlakySink(MemoryOrderSink):
    """켜진(armed) 뒤 n번째 쓰기에서 연결이 끊긴다. commit_then_fail이면 기록을 남긴 뒤 끊긴다."""

    def __init__(self, fail_at: set[int], commit_then_fail: bool = False, armed=True) -> None:
        super().__init__()
        self.writes = 0
        self.fail_at = fail_at
        self.commit_then_fail = commit_then_fail
        self.armed = armed
        self.fail_connects = 0
        self.keys: set = set()

    def connect(self) -> None:
        if self.fail_connects > 0:
            self.fail_connects -= 1
            raise psycopg.OperationalError("connection refused hong@example.com 010-1234-5678")
        super().connect()

    def _write(self, key, record) -> None:
        if key is not None and key in self.keys:  # 이미 커밋된 행 → 23505
            raise psycopg.errors.UniqueViolation("duplicate key hong@example.com")
        if self.armed:
            self.writes += 1
        failing = self.armed and self.writes in self.fail_at
        if failing and not self.commit_then_fail:
            self.fail_connects = 2
            raise psycopg.OperationalError("server closed the connection")
        if key is not None:
            self.keys.add(key)
        record()
        if failing:
            self.fail_connects = 2
            raise psycopg.OperationalError("server closed the connection")

    def create_order(self, order, items) -> None:
        self._write(order.order_id, lambda: MemoryOrderSink.create_order(self, order, items))

    def add_payment(self, payment) -> None:
        self._write(payment.payment_id, lambda: MemoryOrderSink.add_payment(self, payment))

    def update_order_status(self, order_id, status, reason, at) -> None:
        self._write(
            None, lambda: MemoryOrderSink.update_order_status(self, order_id, status, reason, at)
        )


FAIL_AT = {5, 40, 41, 120}


def _run_with(member_ids, catalog, sink, arm_at_drain=False):
    runner, orders, clicks, lines = make(
        member_ids, catalog, steps=[(0, BURST)], mode="burst", visits_daily=3_000, orders=sink
    )
    runner.run_until(MONDAY + timedelta(minutes=30))
    if arm_at_drain:
        sink.armed = True
    runner.drain()
    return runner, orders, clicks, lines


def _collapse_repeated_updates(calls: list[tuple]) -> list[tuple]:
    out: list[tuple] = []
    for call in calls:
        if call[0] == "update_order_status" and out and out[-1] == call:
            continue
        out.append(call)
    return out


def _assert_no_pii(runner, lines) -> None:
    text = "\n".join(lines + runner.summary.lines())
    assert "example.com" not in text and "010-" not in text


@pytest.mark.parametrize("commit_then_fail", [False, True])
def test_reconnect_during_drain_matches_clean_run(member_ids, catalog, commit_then_fail) -> None:
    _, clean, _, _ = _run_with(member_ids, catalog, MemoryOrderSink())
    sink = FlakySink(FAIL_AT, commit_then_fail=commit_then_fail, armed=False)
    runner, flaky, _, lines = _run_with(member_ids, catalog, sink, arm_at_drain=True)
    # 큐 항목은 빠지지도 두 번 반영되지도 않는다. 커밋 직후 끊기면 같은 UPDATE가 한 번 더
    # 실행되지만 같은 값을 다시 쓰는 것이라 DB 결과는 같다 (INSERT는 23505로 건너뛴다)
    assert _collapse_repeated_updates(flaky.calls) == clean.calls
    assert runner.summary.reconnects == len(FAIL_AT)
    waits = [int(m) for line in lines for m in re.findall(r"(\d+)초 뒤 다시 시도", line)]
    assert waits == [1, 2] * len(FAIL_AT)
    _assert_no_pii(runner, lines)


@pytest.mark.parametrize("commit_then_fail", [False, True])
def test_reconnect_while_visiting_keeps_rules(member_ids, catalog, commit_then_fail) -> None:
    sink = FlakySink(FAIL_AT, commit_then_fail=commit_then_fail)
    runner, flaky, clicks, lines = _run_with(member_ids, catalog, sink)
    state = replay(flaky.calls)
    assert consistency_problems(state, clicks.events) == []
    assert len(state) == runner.summary.orders
    assert runner.summary.payments == sum(1 for c in flaky.calls if c[0] == "add_payment")
    finals = {s.status for s in state.values()}
    assert finals <= {"DELIVERED", "CANCELLED", "PAYMENT_FAILED", "REFUNDED"}  # 멈춘 주문 없음
    assert runner.summary.reconnects == len(FAIL_AT)
    _assert_no_pii(runner, lines)


def test_other_db_errors_stop_with_safe_message(member_ids, catalog) -> None:
    class Broken(MemoryOrderSink):
        def add_payment(self, payment) -> None:
            raise psycopg.errors.CheckViolation("value hong@example.com violates")

    from sim.common.db import SafeDatabaseError

    runner, _, _, _ = make(member_ids, catalog, steps=[(0, BURST)], mode="burst", orders=Broken())
    with pytest.raises(SafeDatabaseError) as info:
        runner.run_until(MONDAY + timedelta(hours=1))
    assert "example.com" not in str(info.value)


def test_stop_request_ends_with_summary(member_ids, catalog) -> None:
    runner, _, _, _ = make(member_ids, catalog, steps=[(0, BURST)], mode="burst", duration=600)
    original = runner._visit

    def visit_then_stop() -> None:
        original()
        if runner.summary.visits == 10:
            runner.request_stop()

    runner._visit = visit_then_stop
    summary = runner.run()
    assert summary.visits == 10
    assert summary.lines()[0].startswith("총 방문: 10건")


def test_duration_and_max_visits(member_ids, catalog) -> None:
    runner, _, _, _ = make(member_ids, catalog, duration=120, visits_daily=3_000)
    summary = runner.run()
    assert summary.elapsed_seconds == pytest.approx(120, abs=1e-3)
    runner, _, _, _ = make(member_ids, catalog, max_visits=25, visits_daily=3_000)
    assert runner.run().visits == 25


def test_empty_members_or_catalog_is_an_error(member_ids, catalog) -> None:
    from behavior_fixtures import make_catalog

    with pytest.raises(BehaviorError, match="sim member baseline"):
        make([], catalog)[0].run_until(MONDAY + timedelta(minutes=1))
    with pytest.raises(BehaviorError, match="sim product load"):
        make(member_ids, make_catalog(0))[0].run_until(MONDAY + timedelta(minutes=1))


def test_progress_output_has_no_pii(day) -> None:
    _, _, _, lines = day
    assert any(line.startswith("[진행]") for line in lines)
    text = "\n".join(lines)
    assert "example.com" not in text and "010-" not in text


def test_behavior_does_not_import_other_modules() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "sim" / "behavior"
    forbidden = re.compile(r"^\s*(from|import)\s+sim\.(member|controller|cdc|sink)\b", re.MULTILINE)
    for path in root.glob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name
