"""행동 실행기: 시계 → 제어 신호 → (방문 도착 | 예약 큐) 중 이른 것을 하나씩 실행.

한 프로세스, 한 번에 하나씩이다 (쓰레드·비동기 없음). 예약 큐는 메모리에만 있어서
재시작하면 진행 중이던 주문은 그 상태에 멈춘다 (알려진 한계).
회원 값(PII)은 읽지도 출력하지도 않는다. 오류는 sqlstate와 제약 이름만 다룬다.
"""

import math
import signal
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import FrameType

import psycopg

from sim.behavior import params
from sim.behavior.model import (
    CANCELLED,
    CART_ADD,
    DELIVERED,
    PAID,
    PAYMENT_FAILED,
    SHIPPED,
    SUCCESS,
    AttemptDoneTask,
    AttemptStartTask,
    ClickTask,
    CreateOrderTask,
    NewPayment,
    OrderRef,
    Task,
    Transition,
    TransitionTask,
)
from sim.behavior.payment import (
    NO_EXTRA_FAIL,
    choose_pg,
    decide_attempt,
    next_transition,
    should_retry,
)
from sim.behavior.pool import CatalogSource, MemberPool, MemberSource
from sim.behavior.queue import Entry, ScheduledQueue
from sim.behavior.sink import ClickSink, OrderSink
from sim.behavior.visit import VisitContext, after, build_rankings, plan_visit
from sim.common.clock import SimClock
from sim.common.control import MODES, ControlSource, ControlState
from sim.common.curve import rate_factor
from sim.common.db import SafeDatabaseError, describe_db_error
from sim.common.rng import SimRandom, derive_seed

UNIQUE_VIOLATION = "23505"
TRANSITION_ORDER = (PAID, PAYMENT_FAILED, CANCELLED, SHIPPED, DELIVERED, "REFUNDED")


class BehaviorError(RuntimeError):
    """실행을 계속할 수 없는 오류. 메시지에 PII를 담지 않는다."""


@dataclass
class BehaviorSummary:
    """PII 없는 집계값만 담는다."""

    visits: int = 0
    visits_by_mode: Counter[str] = field(default_factory=Counter)
    views: int = 0
    cart_adds: int = 0
    orders: int = 0
    payments_success: int = 0
    payments_failed: int = 0
    transitions: Counter[str] = field(default_factory=Counter)
    remaining_queue: int = 0
    reconnects: int = 0
    elapsed_seconds: float = 0.0

    @property
    def payments(self) -> int:
        return self.payments_success + self.payments_failed

    def lines(self) -> list[str]:
        modes = ", ".join(f"{m}={n:,}" for m, n in sorted(self.visits_by_mode.items())) or "없음"
        moves = ", ".join(
            f"{s}={self.transitions[s]:,}" for s in TRANSITION_ORDER if self.transitions[s]
        )
        return [
            f"총 방문: {self.visits:,}건 (모드별: {modes})",
            f"클릭: 조회 {self.views:,}건, 담기 {self.cart_adds:,}건",
            f"주문: {self.orders:,}건",
            f"결제 시도: {self.payments:,}건 "
            + f"(성공 {self.payments_success:,}, 실패 {self.payments_failed:,})",
            f"상태 전이: {moves or '없음'}",
            f"남은 큐: {self.remaining_queue:,}건",
            f"재연결: {self.reconnects}회",
            f"실행 시간: {self.elapsed_seconds:.1f}초",
        ]


@contextmanager
def stop_on_signals(runner: "BehaviorRunner") -> Iterator[None]:
    """SIGINT/SIGTERM을 받으면 지금 실행 중인 항목을 끝내고 멈추도록 표시만 한다."""

    def handler(signum: int, frame: FrameType | None) -> None:
        runner.request_stop()

    previous = {s: signal.signal(s, handler) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for s, old in previous.items():
            signal.signal(s, old)


class BehaviorRunner:
    def __init__(
        self,
        orders: OrderSink,
        clicks: ClickSink,
        members: MemberSource,
        catalog: CatalogSource,
        clock: SimClock,
        control: ControlSource,
        *,
        seed: int,
        run_salt: int,
        mode: str = "normal",
        visits_daily: float = params.NORMAL_DAILY_VISITS,
        duration: float | None = None,
        max_visits: int | None = None,
        pg_extra_fail: Mapping[str, float] = NO_EXTRA_FAIL,
        out: Callable[[str], None] = print,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode는 {', '.join(MODES)} 중 하나여야 합니다.")
        if visits_daily <= 0:
            raise ValueError("하루 방문 수는 0보다 커야 합니다.")
        self.orders = orders
        self.clicks = clicks
        self.members = members
        self.catalog_source = catalog
        self.clock = clock
        self.control = control
        self.seed = seed
        self.run_salt = run_salt
        self.mode = mode
        self.visits_daily = visits_daily
        self.duration = duration
        self.max_visits = max_visits
        self.pg_extra_fail = pg_extra_fail  # 장애 주입 자리. 이 브랜치에서는 채우지 않는다
        self.out = out
        self.running = True
        self.summary = BehaviorSummary()
        self.queue = ScheduledQueue()
        self.visit_no = 0
        self.visit_due: datetime | None = None
        self._visits_enabled = True
        self._stop = False
        self._ready = False
        self._ctx: VisitContext | None = None
        self._schedule_rng = SimRandom(derive_seed(seed, "visit-schedule", run_salt))
        self._visit_rng = SimRandom(0)
        self._order_rng = SimRandom(0)
        self._pool_warned = False
        self._last_poll = self._last_progress = self._last_refresh = float("-inf")
        self._progress_mark = BehaviorSummary()

    def request_stop(self) -> None:
        self._stop = True

    # --- 실행 ---

    def run(self) -> BehaviorSummary:
        """--duration, --max-visits, 종료 신호 중 하나가 올 때까지 돈다."""
        self._setup()
        self._loop(self._run_finished)
        return self._finish()

    def run_until(self, sim_end: datetime) -> BehaviorSummary:
        """테스트용: 시뮬레이터 시각 sim_end까지 돈다."""
        self._setup()
        self._loop(lambda: self.clock.now() >= sim_end, sim_end)
        return self._finish()

    def drain(self) -> BehaviorSummary:
        """테스트용: 새 방문을 멈추고 큐가 빌 때까지 처리한다."""
        self._setup()
        self._visits_enabled = False
        self._loop(lambda: len(self.queue) == 0)
        return self._finish()

    def _run_finished(self) -> bool:
        if self.max_visits is not None and self.summary.visits >= self.max_visits:
            return True
        return self.duration is not None and self.clock.real_elapsed() >= self.duration

    def _finish(self) -> BehaviorSummary:
        self.summary.remaining_queue = len(self.queue)
        self.summary.elapsed_seconds = self.clock.real_elapsed()
        return self.summary

    def _setup(self) -> None:
        if self._ready:
            return
        pool = MemberPool(self.seed, self._read_members_or_fail())
        catalog = self.catalog_source.read_catalog()
        if len(catalog) == 0:
            raise BehaviorError("상품이 없습니다. sim product load를 먼저 실행하세요.")
        purchase, views = build_rankings(self.seed, len(catalog))
        self._ctx = VisitContext(pool, catalog, purchase, views)
        self.out(f"회원: {len(pool):,}명  상품: {len(catalog):,}개")
        if not self._open_with_retry(initial=True):
            self._stop = True
        self.clock.restart()  # 읽기와 연결에 든 시간은 실행 시간(--duration)에 넣지 않는다
        self._last_refresh = 0.0
        self._ready = True

    def _read_members_or_fail(self) -> list[str]:
        ids = self.members.read_active_members()
        if not ids:
            raise BehaviorError("회원이 없습니다. sim member baseline을 먼저 실행하세요.")
        return ids

    def _tolerance(self) -> timedelta:
        """가짜 시계의 반올림 오차(µs)를 배속만큼 키운 값. 이 안이면 도착으로 본다."""
        return timedelta(microseconds=2 * math.ceil(self.clock.speed) + 1)

    def _loop(self, done: Callable[[], bool], sim_end: datetime | None = None) -> None:
        while not self._stop and not done():
            self._housekeeping()
            if self._stop or done():
                break
            now = self.clock.now()
            visiting = self._visits_enabled and self.running
            if visiting and self.visit_due is None:
                self.visit_due = now + self._draw_interval(now)
            if visiting and self.visit_due is not None:
                # 처리가 밀려도 제어 확인 주기만큼만 따라잡는다 (밀린 방문을 한꺼번에 쏟지 않는다)
                floor = now - timedelta(seconds=params.CONTROL_POLL_SECONDS * self.clock.speed)
                self.visit_due = max(self.visit_due, floor)
            queue_due = self.queue.peek_due()
            visit_due = self.visit_due if visiting else None
            ready = now + self._tolerance()
            if (
                visit_due is not None
                and visit_due <= ready
                and (queue_due is None or visit_due < queue_due)
            ):
                self._visit()
                continue
            if queue_due is not None and queue_due <= ready:
                self._run_queue_item()
                continue
            self._wait(now, [d for d in (visit_due, queue_due, sim_end) if d is not None])

    def _wait(self, now: datetime, dues: list[datetime]) -> None:
        step = params.CONTROL_POLL_SECONDS
        if dues:
            step = min(step, max((min(dues) - now).total_seconds() / self.clock.speed, 0.0))
        if self.duration is not None and self._visits_enabled:  # drain()은 시간 제한이 없다
            step = min(step, max(self.duration - self.clock.real_elapsed(), 0.0))
        self.clock.sleep(max(step, 1e-6))

    def _housekeeping(self) -> None:
        now_real = self.clock.real_elapsed()
        if now_real - self._last_poll >= params.CONTROL_POLL_SECONDS:
            self._last_poll = now_real
            self._poll_control()
        if self._last_progress == float("-inf"):
            self._last_progress = now_real
        if now_real - self._last_progress >= params.PROGRESS_SECONDS:
            self._print_progress(now_real - self._last_progress)
            self._last_progress = now_real
        if now_real - self._last_refresh >= params.POOL_REFRESH_SECONDS:
            self._last_refresh = now_real
            self._refresh_pool()

    def _draw_interval(self, at: datetime) -> timedelta:
        rate = self.visits_daily * rate_factor(self.mode, at) / params.SECONDS_PER_DAY
        return timedelta(seconds=self._schedule_rng.random.expovariate(rate))

    def _poll_control(self) -> None:
        state: ControlState | None = self.control.read()
        if state is None:
            return
        redraw = state.running != self.running
        if state.mode != self.mode:
            self.out(f"mode: {self.mode} → {state.mode}")
            self.mode = state.mode
            redraw = True
        self.running = state.running
        if redraw:
            self.visit_due = None  # 지금부터 다시 뽑는다 (지수분포는 기억이 없다)

    def _refresh_pool(self) -> None:
        assert self._ctx is not None
        try:
            ids = self.members.read_active_members()
            self._ctx.pool.update(ids)
        except (SafeDatabaseError, psycopg.Error, OSError, ValueError):
            if not self._pool_warned:
                self._pool_warned = True
                self.out("경고: 회원 목록을 다시 읽지 못했습니다. 이전 목록을 유지합니다.")
            return
        self._pool_warned = False

    # --- 방문 ---

    def _visit(self) -> None:
        assert self._ctx is not None and self.visit_due is not None
        k = self.visit_no
        self._visit_rng.reseed(derive_seed(self.seed, "visit", self.run_salt, k))
        plan = plan_visit(self._visit_rng, k, self.visit_due, self._ctx)
        for click in plan.clicks:
            self.queue.push(click.event_time, ClickTask(click))
        if plan.order is not None:
            self.queue.push(plan.order.order.ordered_at, CreateOrderTask(plan.order, k))
        self.visit_no += 1
        self.summary.visits += 1
        self.summary.visits_by_mode[self.mode] += 1
        self.visit_due += self._draw_interval(self.visit_due)

    # --- 예약 큐 ---

    def _run_queue_item(self) -> None:
        entry = self.queue.pop()
        try:
            self._execute(entry)
        except psycopg.OperationalError as error:
            self.queue.push_front(entry)  # 다시 연결되면 이 항목부터 이어서 한다
            self.out(f"DB 연결 오류: {describe_db_error(error)}")
            self._open_with_retry(initial=False)
        except psycopg.Error as error:
            raise SafeDatabaseError(describe_db_error(error)) from None

    def _write(self, action: Callable[..., None], *args: object) -> None:
        """23505(PK/UNIQUE 위반)는 이미 반영된 것으로 본다 (끊기는 순간 커밋됐을 수 있다)."""
        try:
            action(*args)
        except psycopg.Error as error:
            if isinstance(error, psycopg.OperationalError) or error.sqlstate != UNIQUE_VIOLATION:
                raise

    def _rng_for(self, ref: OrderRef, stage: str) -> SimRandom:
        """주문별 후속 추첨의 난수. 처리 순서와 상관없이 같은 입력이면 같은 값이다."""
        seed = derive_seed(self.seed, "order", self.run_salt, ref.visit_no, stage)
        self._order_rng.reseed(seed)
        return self._order_rng

    def _execute(self, entry: Entry) -> None:
        task: Task = entry.task
        if isinstance(task, ClickTask):
            self.clicks.publish(task.event)
            if task.event.event_type == CART_ADD:
                self.summary.cart_adds += 1
            else:
                self.summary.views += 1
        elif isinstance(task, CreateOrderTask):
            self._create_order(task)
        elif isinstance(task, AttemptStartTask):
            self._start_attempt(task, entry.due)
        elif isinstance(task, AttemptDoneTask):
            self._finish_attempt(task)
        elif isinstance(task, TransitionTask):
            self._transition(task)
        else:  # pragma: no cover
            raise TypeError(f"알 수 없는 큐 항목입니다: {type(task).__name__}")

    def _create_order(self, task: CreateOrderTask) -> None:
        plan = task.plan
        self._write(self.orders.create_order, plan.order, plan.items)
        self.summary.orders += 1
        ref = OrderRef(plan.order.order_id, task.visit_no, plan.method, plan.order.total_amount)
        if plan.cancel_at is not None:
            cancel = Transition(CANCELLED, params.CANCEL_REASON, plan.cancel_at)
            self.queue.push(cancel.at, TransitionTask(ref, cancel))
        else:
            self.queue.push(plan.first_attempt_at, AttemptStartTask(ref, 1, None))

    def _start_attempt(self, task: AttemptStartTask, due: datetime) -> None:
        ref, n = task.ref, task.attempt_no
        rng = self._rng_for(ref, f"attempt-{n}")
        pg = choose_pg(rng, n, task.previous_pg)
        result = decide_attempt(rng, n, ref.method, pg, ref.amount, due, self.pg_extra_fail)
        payment = NewPayment(
            rng.uuid4(),
            ref.order_id,
            n,
            ref.method,
            pg,
            ref.amount,
            result.status,
            result.failure_code,
            result.requested_at,
            result.completed_at,
        )
        self.queue.push(payment.completed_at, AttemptDoneTask(ref, payment))

    def _finish_attempt(self, task: AttemptDoneTask) -> None:
        ref, payment = task.ref, task.payment
        self._write(self.orders.add_payment, payment)
        if payment.status == SUCCESS:
            self._write(
                self.orders.update_order_status, ref.order_id, PAID, None, payment.completed_at
            )
            self.summary.payments_success += 1
            self.summary.transitions[PAID] += 1
            follow = next_transition(self._rng_for(ref, "paid"), PAID, payment.completed_at)
            if follow is not None:
                self.queue.push(follow.at, TransitionTask(ref, follow))
            return
        rng = self._rng_for(ref, f"attempt-{payment.attempt_no}-done")
        if should_retry(rng, payment.attempt_no):
            retry_at = after(rng, payment.completed_at, params.RETRY_GAP_SECONDS)
            self.summary.payments_failed += 1
            self.queue.push(retry_at, AttemptStartTask(ref, payment.attempt_no + 1, payment.pg))
            return
        self._write(
            self.orders.update_order_status,
            ref.order_id,
            PAYMENT_FAILED,
            None,
            payment.completed_at,
        )
        self.summary.payments_failed += 1
        self.summary.transitions[PAYMENT_FAILED] += 1

    def _transition(self, task: TransitionTask) -> None:
        ref, move = task.ref, task.transition
        self._write(
            self.orders.update_order_status, ref.order_id, move.status, move.status_reason, move.at
        )
        self.summary.transitions[move.status] += 1
        if move.status in (SHIPPED, DELIVERED):
            follow = next_transition(self._rng_for(ref, move.status.lower()), move.status, move.at)
            if follow is not None:
                self.queue.push(follow.at, TransitionTask(ref, follow))

    # --- 연결 ---

    def _open_with_retry(self, *, initial: bool) -> bool:
        """연결한다. 실패하면 1, 2, 4, … 최대 30초 간격으로 다시 시도한다. 종료 신호면 False."""
        delay = 1
        while True:
            try:
                self.orders.connect()
            except psycopg.Error as error:
                if not isinstance(error, psycopg.OperationalError):
                    raise SafeDatabaseError(describe_db_error(error)) from None
                self.out(f"DB 연결 실패: {describe_db_error(error)} — {delay}초 뒤 다시 시도")
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

    def _print_progress(self, span: float) -> None:
        s, mark = self.summary, self._progress_mark
        self.out(
            f"[진행] mode={self.mode} running={str(self.running).lower()} "
            f"최근 {span:.0f}초 방문 {s.visits - mark.visits:,} 주문 {s.orders - mark.orders:,} "
            f"결제 시도 {s.payments - mark.payments:,} | "
            f"누적 방문 {s.visits:,} 주문 {s.orders:,} 결제 시도 {s.payments:,} "
            f"큐 {len(self.queue):,} 시뮬레이터 시각 {self.clock.now().isoformat(timespec='seconds')}"
        )
        self._progress_mark = BehaviorSummary(
            visits=s.visits, orders=s.orders, payments_success=s.payments, payments_failed=0
        )
