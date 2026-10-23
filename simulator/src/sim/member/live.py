"""신규 가입 실행기: 시계 → 제어 신호 → 간격 대기 → 회원 생성 → INSERT 한 건씩.

회원 값(PII)은 출력하지 않는다. 오류도 sqlstate와 제약 이름만 다룬다.
"""

import signal
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import FrameType
from typing import Protocol

import psycopg
from psycopg import sql

from sim.common.api import PhoneTaken, StoreRejected, StoreUnavailable
from sim.common.clock import SimClock
from sim.common.control import ControlSource, ControlState
from sim.common.db import SafeDatabaseError, db_error_info, describe_db_error
from sim.common.regions import RegionTable
from sim.common.rng import SimRandom, derive_seed
from sim.common.stats import STATS_SECONDS
from sim.member import params
from sim.member.baseline import COLUMNS
from sim.member.generate import draw_phone, generate_member
from sim.member.model import NewMember
from sim.member.schedule import next_interval

CLOCK_TOLERANCE = 1e-6
UNIQUE_VIOLATION = "23505"
PHONE_CONSTRAINT = "members_phone_key"
INSERT_SQL = sql.SQL("INSERT INTO members ({}) VALUES ({})").format(
    sql.SQL(", ").join(sql.Identifier(c) for c in COLUMNS),
    sql.SQL(", ").join(sql.Placeholder() for _ in COLUMNS),
)
COUNT_SQL = "SELECT count(*) FROM members WHERE signup_at >= %s"


class LiveError(RuntimeError):
    """실행을 계속할 수 없는 오류. 메시지에 PII를 담지 않는다."""


class MemberStore(Protocol):
    """실행기가 DB에 바라는 것 둘. psycopg.Error를 그대로 던질 수 있다."""

    def connect(self) -> None: ...

    def count_since(self, since: datetime) -> int: ...

    def insert(self, member: NewMember) -> None:
        """한 건 = 한 트랜잭션 (자동 커밋)."""
        ...


class DbStore:
    """로컬 PostgreSQL에 자동 커밋으로 한 건씩 넣는다."""

    def __init__(self, database_url: str, schema: str | None = None) -> None:
        self._url = database_url
        self._schema = schema
        self._conn: psycopg.Connection | None = None

    def connect(self) -> None:
        self.close()
        conn = psycopg.connect(self._url, autocommit=True)
        if self._schema:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema)))
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except psycopg.Error:
                pass
            self._conn = None

    def _require(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            raise psycopg.OperationalError("연결이 없습니다")
        return self._conn

    def count_since(self, since: datetime) -> int:
        row = self._require().execute(COUNT_SQL, (since,)).fetchone()
        return int(row[0]) if row else 0

    def insert(self, member: NewMember) -> None:
        values = tuple(getattr(member, column) for column in COLUMNS)
        self._require().execute(INSERT_SQL, values)


@dataclass
class LiveSummary:
    """PII 없는 집계값만 담는다."""

    total: int = 0
    by_mode: Counter[str] = field(default_factory=Counter)
    elapsed_seconds: float = 0.0
    reconnects: int = 0
    phone_retries: int = 0
    start_index: int = 0

    def lines(self) -> list[str]:
        modes = ", ".join(f"{m}={n:,}" for m, n in sorted(self.by_mode.items())) or "없음"
        return [
            f"총 가입: {self.total:,}건 (시작 인덱스 {self.start_index:,})",
            f"모드별: {modes}",
            f"실행 시간: {self.elapsed_seconds:.1f}초",
            f"재연결: {self.reconnects}회  전화번호 재시도: {self.phone_retries}회",
        ]


@contextmanager
def stop_on_signals(runner: "LiveRunner") -> Iterator[None]:
    """SIGINT/SIGTERM을 받으면 지금 하던 INSERT를 끝내고 멈추도록 표시만 한다."""

    def handler(signum: int, frame: FrameType | None) -> None:
        runner.request_stop()

    previous = {s: signal.signal(s, handler) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for s, old in previous.items():
            signal.signal(s, old)


class LiveRunner:
    def __init__(
        self,
        store: MemberStore,
        regions: RegionTable,
        clock: SimClock,
        control: ControlSource,
        *,
        seed: int,
        mode: str = "normal",
        daily: float = params.NORMAL_DAILY_SIGNUPS,
        duration: float | None = None,
        max_signups: int | None = None,
        out: Callable[[str], None] = print,
        stats: Callable[[dict], None] | None = None,
    ) -> None:
        self.store = store
        self.regions = regions
        self.clock = clock
        self.control = control
        self.seed = seed
        self.mode = mode
        self.daily = daily
        self.duration = duration
        self.max_signups = max_signups
        self.out = out
        self.stats = stats  # 컨트롤러 화면용 누적 숫자 (StatsFile.write). 없으면 쓰지 않는다
        self.running = True
        self.summary = LiveSummary()
        self.next_index = 0
        self._stop = False
        self._member_rng = SimRandom(seed)
        self._schedule_rng = SimRandom(seed)

    def request_stop(self) -> None:
        self._stop = True

    # --- 실행 ---

    def run(self) -> LiveSummary:
        if self.clock.now() < params.BASELINE_END:
            raise LiveError(
                "시뮬레이터 시각이 베이스라인 끝(2026-10-01 KST)보다 이릅니다. "
                "시작 인덱스를 셀 수 없어 멈춥니다."
            )
        if not self._open_with_retry(initial=True):
            return self.summary
        self._schedule_rng.reseed(derive_seed(self.seed, "live-schedule", self.next_index))
        self.summary.start_index = self.next_index
        self.out(f"시작 인덱스: {self.next_index:,}")

        self.clock.restart()  # 연결과 초기화에 든 시간은 실행 시간(--duration)에 넣지 않는다
        due: float | None = None  # 다음 가입 시각 (실제 경과 초). None이면 새로 뽑는다
        last_poll = last_progress = last_stats = float("-inf")
        progress_count = 0
        while not self._should_stop():
            now_real = self.clock.real_elapsed()
            if now_real - last_poll >= params.CONTROL_POLL_SECONDS:
                last_poll = now_real
                if self._poll_control():
                    due = None
            if last_progress == float("-inf"):
                last_progress = now_real
            if now_real - last_progress >= params.LIVE_PROGRESS_SECONDS:
                span = now_real - last_progress
                self._print_progress(self.summary.total - progress_count, span)
                last_progress, progress_count = now_real, self.summary.total
            if self.stats is not None and now_real - last_stats >= STATS_SECONDS:
                last_stats = now_real
                self.stats(self.stats_data())

            if not self.running:
                due = None
                self.clock.sleep(params.CONTROL_POLL_SECONDS)
                continue
            if due is None:
                due = now_real + self._draw_wait()
            step = min(max(due - now_real, 0.0), params.CONTROL_POLL_SECONDS)
            if self.duration is not None:
                step = min(step, max(self.duration - now_real, 0.0))
            self.clock.sleep(step)
            if (
                due - self.clock.real_elapsed() > CLOCK_TOLERANCE
            ):  # 시계 해상도(1µs) 이하는 도착으로 본다
                continue
            if self._should_stop():
                break
            self._signup_once()
            # 가입에 걸린 시간이 도착 간격에 더해지지 않도록 마감 시각에서 이어 잰다.
            # 처리가 밀려도 따라잡는 폭은 제어 확인 주기(1초)까지만 둔다.
            base = max(due, self.clock.real_elapsed() - params.CONTROL_POLL_SECONDS)
            due = base + self._draw_wait()

        self.summary.elapsed_seconds = self.clock.real_elapsed()
        return self.summary

    def stats_data(self) -> dict:
        """컨트롤러 화면용 누적 숫자. PII 없음."""
        return {
            "mode": self.mode,
            "running": self.running,
            "signups": self.summary.total,
            "reconnects": self.summary.reconnects,
        }

    def _should_stop(self) -> bool:
        if self._stop:
            return True
        if self.max_signups is not None and self.summary.total >= self.max_signups:
            return True
        return self.duration is not None and self.clock.real_elapsed() >= self.duration

    def _draw_wait(self) -> float:
        interval = next_interval(self._schedule_rng, self.daily, self.mode, self.clock.now())
        return interval / self.clock.speed

    def _poll_control(self) -> bool:
        """제어 신호를 읽는다. 간격을 다시 뽑아야 하면 True."""
        state: ControlState | None = self.control.read()
        if state is None:
            return False
        redraw = state.running != self.running
        if state.mode != self.mode:
            self.out(f"mode: {self.mode} → {state.mode}")
            self.mode = state.mode
            redraw = True
        self.running = state.running
        return redraw

    # --- 가입 한 건 ---

    def _build(self, index: int) -> NewMember:
        """k번째 회원. 값은 시드와 k만으로 정해진다 (가입 시각만 시계에서 온다)."""
        rng = self._member_rng
        rng.reseed(derive_seed(self.seed, "live", index))
        phone = draw_phone(rng)
        return generate_member(rng, self.clock.now(), self.regions, phone)

    def _signup_once(self) -> bool:
        member = self._build(self.next_index)
        retries = 0
        while True:
            try:
                self.store.insert(member)
            except psycopg.OperationalError as error:
                self.out(f"DB 연결 오류: {describe_db_error(error)}")
                self._open_with_retry(initial=False)
                return False  # 연결이 끊긴 동안 만든 회원은 없다. 인덱스는 다시 센 값이다
            except StoreUnavailable as error:  # --backend api: 끊긴 동안의 가입은 다시 센다
                self.out(f"API 연결 오류: {error}")
                self._open_with_retry(initial=False)
                return False
            except PhoneTaken:
                if retries >= params.PHONE_RETRY_LIMIT:
                    raise LiveError(
                        f"전화번호 중복이 {params.PHONE_RETRY_LIMIT}번 재시도 후에도 풀리지 않았습니다."
                    ) from None
                retries += 1
                self.summary.phone_retries += 1
                member = replace(member, phone=draw_phone(self._member_rng))
            except StoreRejected as error:
                raise LiveError(str(error)) from None
            except psycopg.Error as error:
                info = db_error_info(error)
                is_phone = info.sqlstate == UNIQUE_VIOLATION and info.constraint == PHONE_CONSTRAINT
                if not is_phone:
                    raise SafeDatabaseError(describe_db_error(error)) from None
                if retries >= params.PHONE_RETRY_LIMIT:
                    raise LiveError(
                        f"전화번호 중복이 {params.PHONE_RETRY_LIMIT}번 재시도 후에도 풀리지 않았습니다."
                    ) from None
                retries += 1
                self.summary.phone_retries += 1
                member = replace(member, phone=draw_phone(self._member_rng))
            else:
                self.next_index += 1
                self.summary.total += 1
                self.summary.by_mode[self.mode] += 1
                return True

    # --- 연결 ---

    def _open_with_retry(self, *, initial: bool) -> bool:
        """연결하고 시작 인덱스를 센다. 실패하면 1, 2, 4, … 최대 30초 간격으로 다시 시도한다.

        기다리는 중 종료 신호를 받으면 False. 끊긴 순간 커밋됐을 수 있는 가입이 있으므로
        다시 연결할 때마다 인덱스를 DB에서 다시 센다.
        """
        delay = 1
        while True:
            try:
                self.store.connect()
                self.next_index = self.store.count_since(params.BASELINE_END)
            except (psycopg.Error, StoreUnavailable) as error:
                if isinstance(error, psycopg.Error) and not isinstance(
                    error, psycopg.OperationalError
                ):
                    raise SafeDatabaseError(describe_db_error(error)) from None
                if isinstance(error, psycopg.Error):
                    reason = f"DB 연결 실패: {describe_db_error(error)}"
                else:
                    reason = f"API 연결 실패: {error}"
                self.out(f"{reason} — {delay}초 뒤 다시 시도")
                self._sleep_interruptible(delay)
                if self._stop:
                    return False
                delay = min(delay * 2, params.RECONNECT_MAX_WAIT_SECONDS)
                continue
            if not initial:
                self.summary.reconnects += 1
                self.out("DB 다시 연결됨")
            return True

    def _sleep_interruptible(self, seconds: float) -> None:
        remaining = float(seconds)
        while remaining > 0 and not self._stop:
            step = min(remaining, params.CONTROL_POLL_SECONDS)
            self.clock.sleep(step)
            remaining -= step

    # --- 출력 ---

    def _print_progress(self, count: int, span: float) -> None:
        rate = count / span if span > 0 else 0.0
        self.out(
            f"[진행] mode={self.mode} running={str(self.running).lower()} "
            f"최근 {span:.0f}초 {count:,}건 ({rate:.2f}건/초) 누적 {self.summary.total:,}건 "
            f"시뮬레이터 시각 {self.clock.now().isoformat(timespec='seconds')}"
        )
