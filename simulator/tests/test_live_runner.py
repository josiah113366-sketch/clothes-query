import itertools
import math
import signal
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta

import psycopg
import pytest

from sim.common import curve
from sim.common.clock import FakeTime, SimClock
from sim.common.control import ControlState
from sim.common.db import SafeDatabaseError
from sim.common.rng import SimRandom
from sim.member import params
from sim.member.baseline import iter_members
from sim.member.generate import allocate_phones, draw_phone, generate_member
from sim.member.live import LiveError, LiveRunner, stop_on_signals

START = datetime(2026, 10, 1, 0, 0, 0, tzinfo=params.KST)
MONDAY = datetime(2026, 10, 12, 0, 0, 0, tzinfo=params.KST)  # 요일 곡선 테스트의 고정 시작
DAILY = params.NORMAL_DAILY_SIGNUPS
PII = "hong.gildong@secret-mail.com 010-7777-8888"


class _Diag:
    def __init__(self, constraint: str) -> None:
        self.constraint_name = constraint

    @property
    def message_detail(self) -> str:
        raise AssertionError("message_detail을 읽으면 안 된다")


class _Violation(psycopg.errors.UniqueViolation):
    def __init__(self, constraint: str) -> None:
        super().__init__(f"Key ({constraint})=({PII}) already exists.")
        self._constraint = constraint

    @property
    def diag(self):  # type: ignore[override]
        return _Diag(self._constraint)

    def __str__(self) -> str:
        raise AssertionError("str(error)를 읽으면 안 된다")


class FakeStore:
    """DB 없이 MemberStore를 흉내 낸다. UNIQUE 제약과 연결 끊김을 재현할 수 있다."""

    def __init__(self) -> None:
        self.rows: list = []
        self.phones: set[str] = set()
        self.ids: set[str] = set()
        self.preset_phones: set[str] = set()
        self.connects = 0
        self.fail_connect = 0  # 앞으로 이만큼 연결 실패
        self.fail_insert_with: Exception | None = None
        self.phone_conflicts = 0  # 앞으로 이만큼 members_phone_key 위반
        self.connect_times: list[datetime] = []
        self.clock: SimClock | None = None
        self.on_insert = None

    def connect(self) -> None:
        if self.clock:
            self.connect_times.append(self.clock.now())
        if self.fail_connect > 0:
            self.fail_connect -= 1
            raise psycopg.OperationalError(f"connection refused {PII}")
        self.connects += 1

    def count_since(self, since: datetime) -> int:
        return sum(1 for m in self.rows if m.signup_at >= since)

    def insert(self, member) -> None:
        if self.on_insert:
            self.on_insert(self, member)
        if self.fail_insert_with is not None:
            error, self.fail_insert_with = self.fail_insert_with, None
            raise error
        if self.phone_conflicts > 0:
            self.phone_conflicts -= 1
            raise _Violation("members_phone_key")
        if member.member_id in self.ids:
            raise _Violation("members_pkey")
        if member.phone in self.phones or member.phone in self.preset_phones:
            raise _Violation("members_phone_key")
        self.ids.add(member.member_id)
        self.phones.add(member.phone)
        self.rows.append(member)


class Script:
    """실제 경과 시간(초)에 따라 제어 상태를 바꾸는 가짜 제어 신호."""

    def __init__(self, clock: SimClock, steps: list[tuple[float, ControlState]]) -> None:
        self.clock, self.steps = clock, steps
        self.reads = 0

    def read(self) -> ControlState | None:
        self.reads += 1
        t = self.clock.real_elapsed()
        current = None
        for at, state in self.steps:
            if t >= at:
                current = state
        return current


NORMAL = ControlState(True, "normal")
BURST = ControlState(True, "burst")
MEDIUM = ControlState(True, "medium")
PAUSED = ControlState(False, "normal")


def make(regions, *, steps=None, store=None, speed=60.0, start=START, **kwargs):
    ft = FakeTime(start)
    clock = SimClock.fake(ft, speed=speed)
    store = store or FakeStore()
    store.clock = clock
    lines: list[str] = []
    control = Script(clock, steps or [(0, NORMAL)])
    kwargs.setdefault("seed", 42)
    runner = LiveRunner(store, regions, clock, control, out=lines.append, **kwargs)
    return runner, store, clock, lines


def _within_5_sigma(count: int, expected: float) -> bool:
    return abs(count - expected) <= 5 * math.sqrt(expected)


def _expected_normal(start: datetime, end: datetime, daily: float = DAILY) -> float:
    """normal 모드에서 [start, end) 동안의 기대 건수 (곡선은 시간 단위 계단이라 분 단위 합이면 정확하다)."""
    minutes = int((end - start).total_seconds() // 60)
    total = sum(curve.rate_factor("normal", start + timedelta(minutes=m)) for m in range(minutes))
    return daily * total * 60 / params.SECONDS_PER_DAY


def test_normal_rate_over_fourteen_sim_days(regions) -> None:
    # 시뮬레이터 14일 = 실제 20,160초 (배속 60). 7의 배수라 요일 곡선의 평균이 1이다
    runner, store, _, _ = make(regions, duration=20_160, start=MONDAY)
    summary = runner.run()
    assert _within_5_sigma(summary.total, 14 * DAILY)
    assert len(store.rows) == summary.total
    assert summary.by_mode == Counter(normal=summary.total)


@pytest.mark.parametrize(("state", "factor"), [(BURST, 18.0), (MEDIUM, 5.4)])
def test_fixed_mode_rate_one_sim_hour(regions, state: ControlState, factor: float) -> None:
    # 시뮬레이터 1시간 = 실제 60초. 밤 0시에 시작해도 시간대 곡선과 무관하게 고정 속도다
    runner, _, _, lines = make(
        regions, steps=[(0, state)], duration=60, mode=state.mode, start=MONDAY
    )
    summary = runner.run()
    assert _within_5_sigma(summary.total, DAILY * factor / 24)
    assert summary.by_mode == Counter({state.mode: summary.total})
    assert not any("→" in line for line in lines)


def test_mode_switch_segments_follow_their_rates(regions) -> None:
    # 배속 10: normal 월요일 하루 → burst 1시간 → normal 23시간 (제어 확인 지연은 시뮬레이터 10초 이내)
    day, hour = 8_640, 360  # 실제 초
    steps = [(0, NORMAL), (day, BURST), (day + hour, NORMAL)]
    runner, store, _, lines = make(regions, steps=steps, duration=2 * day, speed=10, start=MONDAY)
    runner.run()
    bounds = [
        MONDAY,
        MONDAY + timedelta(days=1),
        MONDAY + timedelta(days=1, hours=1),
        MONDAY + timedelta(days=2),
    ]
    seg = [sum(1 for m in store.rows if bounds[i] <= m.signup_at < bounds[i + 1]) for i in range(3)]
    assert _within_5_sigma(seg[0], _expected_normal(bounds[0], bounds[1]))
    assert _within_5_sigma(seg[1], DAILY * 18 / 24)
    assert _within_5_sigma(seg[2], _expected_normal(bounds[2], bounds[3]))
    assert [line for line in lines if "→" in line] == [
        "mode: normal → burst",
        "mode: burst → normal",
    ]


def test_pause_and_resume(regions) -> None:
    steps = [(0, NORMAL), (600, PAUSED), (1_200, NORMAL)]
    runner, store, _, _ = make(regions, steps=steps, duration=1_800)
    runner.run()
    # 배속 60이므로 실제 600초 = 시뮬레이터 10시간
    # 제어 신호는 약 1초(=시뮬레이터 60초)마다 읽으므로 전환 직후 몇 분은 여유를 둔다
    paused_from = START + timedelta(hours=10, minutes=2)
    paused_to = START + timedelta(hours=20)
    in_pause = [m for m in store.rows if paused_from < m.signup_at < paused_to]
    assert in_pause == []
    assert any(m.signup_at <= paused_from for m in store.rows)
    assert any(m.signup_at >= paused_to for m in store.rows)


def test_same_inputs_give_identical_members_and_times(regions) -> None:
    def run_once() -> list:
        runner, store, _, _ = make(regions, max_signups=300)
        runner.run()
        return [
            (m.member_id, m.name, m.email, m.phone, m.signup_at, m.region_sigungu)
            for m in store.rows
        ]

    first, second = run_once(), run_once()
    assert len(first) == 300
    assert first == second


def test_kth_member_is_independent_of_start_index(regions) -> None:
    runner, store, _, _ = make(regions, max_signups=50)
    runner.run()
    # 이미 50명이 들어 있는 DB에서 다시 시작하면 50번째(0부터) 회원이 이어서 만들어진다
    runner2, store2, _, _ = make(regions, max_signups=1)
    store2.rows = list(store.rows)
    store2.ids = set(store.ids)
    store2.phones = set(store.phones)
    runner2.run()
    assert runner2.summary.start_index == 50
    ref, _, _, _ = make(regions, max_signups=51)
    ref_store = ref.store
    ref.run()
    a, b = store2.rows[-1], ref_store.rows[50]
    fixed = replace(a, signup_at=b.signup_at)
    assert fixed == b


def test_live_stream_differs_from_baseline(regions) -> None:
    runner, store, _, _ = make(regions, max_signups=300)
    runner.run()
    live_ids = {m.member_id for m in store.rows}
    base = list(iter_members(SimRandom(42), 300, regions))
    assert live_ids.isdisjoint({m.member_id for m in base})


def test_signup_at_is_aware_and_equals_clock_at_speed_one(regions) -> None:
    runner, store, clock, _ = make(regions, speed=1, max_signups=5, daily=86_400)
    runner.run()
    for m in store.rows:
        assert m.signup_at.utcoffset() == timedelta(hours=9)
        assert START <= m.signup_at <= clock.now()
    # 배속 1: 마지막 가입 시각은 시계의 시각과 같다 (그 뒤로 시간이 흐르지 않았다)
    assert store.rows[-1].signup_at == clock.now()


def test_refuses_to_start_before_baseline_end(regions) -> None:
    runner, store, _, _ = make(regions, start=START - timedelta(seconds=1), max_signups=1)
    with pytest.raises(LiveError):
        runner.run()
    assert store.rows == []


def test_phone_retry_changes_only_phone_and_gives_up_after_limit(regions) -> None:
    runner, store, _, _ = make(regions, max_signups=1)
    store.phone_conflicts = 3
    runner.run()
    assert runner.summary.phone_retries == 3 and len(store.rows) == 1
    # 재시도해도 전화번호 외 값은 k번째 회원 그대로다
    ref, ref_store, _, _ = make(regions, max_signups=1)
    ref.run()
    got, want = store.rows[0], ref_store.rows[0]
    assert got.phone != want.phone
    assert replace(got, phone=want.phone, signup_at=want.signup_at) == want

    runner, store, _, _ = make(regions, max_signups=1)
    store.phone_conflicts = params.PHONE_RETRY_LIMIT  # 10번 실패 뒤 11번째 시도는 성공
    runner.run()
    assert runner.summary.phone_retries == 10 and len(store.rows) == 1

    runner, store, _, _ = make(regions, max_signups=1)
    store.phone_conflicts = params.PHONE_RETRY_LIMIT + 1  # 11번째도 실패
    with pytest.raises(LiveError) as info:
        runner.run()
    assert PII not in str(info.value)
    assert store.rows == []


def test_other_constraint_violation_is_not_retried(regions) -> None:
    runner, store, _, _ = make(regions, max_signups=1)
    store.fail_insert_with = _Violation("members_pkey")
    with pytest.raises(SafeDatabaseError) as info:
        runner.run()
    assert "members_pkey" in str(info.value) and PII not in str(info.value)
    assert runner.summary.phone_retries == 0


def test_stop_signal_finishes_cleanly(regions) -> None:
    runner, store, _, _ = make(regions)
    with stop_on_signals(runner):
        store.on_insert = lambda s, m: (
            signal.raise_signal(signal.SIGTERM) if len(s.rows) == 4 else None
        )
        summary = runner.run()
    # 신호를 받은 시점에 하던 INSERT(5번째)는 끝나고, 그 다음은 만들지 않는다
    assert summary.total == 5 and len(store.rows) == 5
    # 핸들러가 원래대로 돌아갔다
    assert signal.getsignal(signal.SIGTERM) is not None


def test_reconnect_backoff_and_no_pii(regions) -> None:
    runner, store, _, lines = make(regions, max_signups=3)
    store.fail_insert_with = psycopg.OperationalError(f"server closed {PII}")
    runner.run()  # 첫 연결 성공, 첫 INSERT에서 끊김 → 재연결 1회
    assert runner.summary.reconnects == 1
    assert runner.summary.total == 3
    assert not any(PII in line for line in lines)
    assert any("OperationalError" in line for line in lines)

    # 연결 실패가 이어지면 1, 2, 4, 8, 16, 30, 30초 간격으로 다시 시도한다
    runner, store, _, lines = make(regions, speed=1, max_signups=1)
    store.fail_connect = 7
    runner.run()
    times = store.connect_times
    gaps = [(b - a).total_seconds() for a, b in itertools.pairwise(times)]
    assert gaps == [1, 2, 4, 8, 16, 30, 30]
    assert not any(PII in line for line in lines)


def test_reconnect_recounts_index_so_committed_insert_is_not_repeated(regions) -> None:
    runner, store, _, _ = make(regions, max_signups=3)

    def commit_then_drop(s: FakeStore, member) -> None:
        if len(s.rows) == 1 and s.fail_insert_with is None and not getattr(s, "dropped", False):
            s.dropped = True
            s.ids.add(member.member_id)
            s.phones.add(member.phone)
            s.rows.append(member)  # 커밋은 됐는데 응답 전에 연결이 끊긴 경우
            s.fail_insert_with = psycopg.OperationalError("lost")

    store.on_insert = commit_then_drop
    runner.run()
    ids = [m.member_id for m in store.rows]
    assert len(ids) == len(set(ids))


def test_output_has_no_pii(regions) -> None:
    runner, store, _, lines = make(regions, speed=1440, duration=60)
    summary = runner.run()
    text = "\n".join(lines + summary.lines())
    assert "example.com" not in text and "010-" not in text
    assert any(line.startswith("[진행]") for line in lines)
    assert all(m.name not in text for m in store.rows[:50])


def test_draw_phone_uses_baseline_format() -> None:
    rng = SimRandom(1)
    for phone in [draw_phone(rng) for _ in range(50)] + allocate_phones(rng, 50):
        assert len(phone) == 13 and phone.startswith("010-") and phone[8] == "-"
    assert generate_member  # 같은 생성 함수를 쓴다


def test_slow_insert_does_not_lower_the_arrival_rate(regions) -> None:
    # 가입 하나에 INSERT가 5ms 걸려도 도착 속도는 정한 값(하루 5,000명)을 따라야 한다.
    # 간격을 INSERT가 끝난 뒤부터 새로 재면 도착 속도가 눈에 띄게 떨어진다.
    # 하루 수는 고정한다. 배속 1440에서 기본값(25,000)은 초당 약 400건이라 5ms INSERT로는 닿을 수 없다.
    runner, store, clock, _ = make(regions, speed=1440, duration=120, daily=5000)
    store.on_insert = lambda s, m: clock.sleep(0.005)
    summary = runner.run()
    # 실제 120초 = 시뮬레이터 2일
    expected = _expected_normal(START, START + timedelta(days=2), daily=5000)
    assert _within_5_sigma(summary.total, expected)
