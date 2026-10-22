import math
from collections import Counter
from datetime import datetime, timedelta

import pytest

from sim.behavior import params
from sim.behavior.model import (
    CANCELLED,
    DELIVERED,
    FAILED,
    PAID,
    PAYMENT_FAILED,
    REFUNDED,
    SHIPPED,
    SUCCESS,
)
from sim.behavior.payment import choose_pg, decide_attempt, next_transition, should_retry
from sim.common.rng import SimRandom
from sim.common.timezone import KST

T0 = datetime(2026, 10, 12, 20, 0, 0, tzinfo=KST)
N = 200_000


def _within(hits: int, n: int, p: float) -> bool:
    return abs(hits - n * p) <= 5 * math.sqrt(n * p * (1 - p))


def _attempts(attempt_no: int, method: str = "CARD", pg: str = "PG_A", extra=None, seed=1):
    rng = SimRandom(seed)
    kwargs = {} if extra is None else {"pg_extra_fail": extra}
    return [decide_attempt(rng, attempt_no, method, pg, 10_000, T0, **kwargs) for _ in range(N)]


def _causes(results) -> Counter:
    pg_codes = {c for c, _ in params.PG_FAILURE_CODES}
    return Counter(
        "ok" if r.status == SUCCESS else ("pg" if r.failure_code in pg_codes else "customer")
        for r in results
    )


@pytest.fixture(scope="module")
def first() -> list:
    return _attempts(1)


def test_first_attempt_failure_rates(first) -> None:
    causes = _causes(first)
    assert _within(causes["customer"], N, 0.07)
    assert _within(causes["pg"], N, 0.01)
    assert _within(causes["ok"], N, 0.92)


def test_retry_success_rate() -> None:
    causes = _causes(_attempts(2))
    assert _within(causes["ok"], N, 0.70)
    assert _within(causes["customer"], N, 0.2625)
    assert _within(causes["pg"], N, 0.0375)


def test_failure_code_distribution(first) -> None:
    codes = Counter(r.failure_code for r in first if r.status == FAILED)
    customer = sum(codes[c] for c, _ in params.CUSTOMER_FAILURE_CODES)
    for code, p in params.CUSTOMER_FAILURE_CODES:
        assert _within(codes[code], customer, p), code
    pg = sum(codes[c] for c, _ in params.PG_FAILURE_CODES)
    for code, p in params.PG_FAILURE_CODES:
        assert _within(codes[code], pg, p), code


def test_bank_transfer_customer_code_is_insufficient_balance() -> None:
    results = _attempts(1, method="BANK_TRANSFER")
    codes = {r.failure_code for r in results if r.status == FAILED}
    assert codes <= {"INSUFFICIENT_BALANCE", "PG_TIMEOUT", "PG_ERROR"}
    assert "INSUFFICIENT_BALANCE" in codes


def test_attempt_duration_and_fields(first) -> None:
    for r in first[:20_000]:
        assert 2 <= (r.completed_at - r.requested_at).total_seconds() <= 5
        assert r.requested_at == T0 and r.pg == "PG_A"
        assert (r.status == SUCCESS) == (r.failure_code is None)


def test_pg_choice() -> None:
    rng = SimRandom(3)
    firsts = Counter(choose_pg(rng, 1, None) for _ in range(N))
    assert _within(firsts["PG_A"], N, 0.5)
    switched = sum(1 for _ in range(N) if choose_pg(rng, 2, "PG_A") == "PG_B")
    assert _within(switched, N, params.RETRY_SWITCH_PG)


def test_pg_extra_fail_raises_only_that_pg() -> None:
    extra = {"PG_A": 0.5}
    for attempt_no, base in ((1, 0.01), (2, 0.0375)):
        a = _causes(_attempts(attempt_no, pg="PG_A", extra=extra))
        b = _causes(_attempts(attempt_no, pg="PG_B", extra=extra))
        assert _within(a["pg"], N, base + 0.5)
        assert _within(b["pg"], N, base)
    # 비어 있으면 기본과 똑같다
    assert _attempts(1, extra={}) == _attempts(1)


def test_invalid_attempt_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide_attempt(SimRandom(1), 4, "CARD", "PG_A", 10_000, T0)
    with pytest.raises(ValueError):
        decide_attempt(SimRandom(1), 1, "CARD", "PG_A", 0, T0)


def _simulate_orders(n: int, seed: int = 11) -> tuple[int, int, int]:
    """결제 단계에 간 주문 n개를 끝까지 시도한다. (시도 수, 실패 시도 수, 최종 실패 주문 수)."""
    rng = SimRandom(seed)
    attempts = failed_attempts = failed_orders = 0
    for _ in range(n):
        attempt_no, pg = 1, None
        while True:
            pg = choose_pg(rng, attempt_no, pg)
            result = decide_attempt(rng, attempt_no, "CARD", pg, 10_000, T0)
            attempts += 1
            if result.status == SUCCESS:
                break
            failed_attempts += 1
            if not should_retry(rng, attempt_no):
                failed_orders += 1
                break
            attempt_no += 1
    return attempts, failed_attempts, failed_orders


def test_order_level_payment_baselines() -> None:
    n = N
    attempts, failed_attempts, failed_orders = _simulate_orders(n)
    # 기대값: 시도 1.0566회/주문, 시도 실패율 9.18%, 주문 최종 실패 4.04%
    p_retry1 = 0.08 * 0.6
    expected_attempts = 1 + p_retry1 + p_retry1 * 0.3 * 0.6
    assert attempts / n == pytest.approx(expected_attempts, abs=5 * math.sqrt(0.06 / n))
    assert expected_attempts == pytest.approx(1.057, abs=1e-3)
    assert _within(failed_attempts, attempts, 0.0918)
    assert _within(failed_orders, n, 0.08 * (0.4 + 0.6 * 0.3 * (0.4 + 0.6 * 0.3)))
    assert failed_orders / n == pytest.approx(0.040, abs=0.003)


def test_max_three_attempts() -> None:
    rng = SimRandom(1)
    assert not any(should_retry(rng, 3) for _ in range(1_000))
    assert _within(sum(should_retry(rng, 1) for _ in range(N)), N, params.RETRY_RATE)


def _transitions(state: str, seed: int = 5):
    rng = SimRandom(seed)
    return [next_transition(rng, state, T0) for _ in range(N)]


def _hours(t) -> float:
    return (t.at - T0).total_seconds() / 3600


def test_paid_transitions() -> None:
    results = _transitions(PAID)
    cancelled = [t for t in results if t.status == CANCELLED]
    shipped = [t for t in results if t.status == SHIPPED]
    assert len(cancelled) + len(shipped) == N
    assert _within(len(cancelled), N, params.PAID_CANCEL_RATE)
    assert all(t.status_reason == "USER_REQUEST" and 1 / 6 <= _hours(t) <= 3 for t in cancelled)
    assert all(t.status_reason is None and 2 <= _hours(t) <= 6 for t in shipped)


def test_delivery_and_refund() -> None:
    delivered = _transitions(SHIPPED)
    assert all(t.status == DELIVERED and 3 <= _hours(t) <= 6 for t in delivered)
    refunds = [t for t in _transitions(DELIVERED) if t is not None]
    assert _within(len(refunds), N, params.REFUND_RATE)
    assert all(t.status == REFUNDED and t.status_reason == "RETURN" for t in refunds)
    assert all(2 <= _hours(t) <= 36 for t in refunds)


def test_shipping_to_delivery_is_5_to_12_hours_after_payment() -> None:
    rng = SimRandom(8)
    for _ in range(20_000):
        t = next_transition(rng, PAID, T0)
        if t.status != SHIPPED:
            continue
        d = next_transition(rng, SHIPPED, t.at)
        assert timedelta(hours=5) <= d.at - T0 <= timedelta(hours=12)


@pytest.mark.parametrize("state", [CANCELLED, PAYMENT_FAILED, REFUNDED])
def test_no_transition_after_terminal_state(state: str) -> None:
    rng = SimRandom(1)
    assert all(next_transition(rng, state, T0) is None for _ in range(100))
