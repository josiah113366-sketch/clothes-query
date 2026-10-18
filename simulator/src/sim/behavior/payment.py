"""결제 시도와 상태 전이 추첨. 순수 함수다.

결제 결과는 큐에서 시도를 실행하는 시점에 추첨한다 (주문 생성 때 미리 정하지 않는다).
그래야 나중에 PG 장애 구간에 시도되는 결제만 pg_extra_fail의 영향을 받는다.
"""

from collections.abc import Mapping
from datetime import datetime
from itertools import accumulate
from types import MappingProxyType

from sim.behavior import params
from sim.behavior.model import (
    CANCELLED,
    DELIVERED,
    FAILED,
    PAID,
    REFUNDED,
    SHIPPED,
    SUCCESS,
    AttemptResult,
    Transition,
)
from sim.behavior.visit import after
from sim.common.rng import SimRandom

NO_EXTRA_FAIL: Mapping[str, float] = MappingProxyType({})

_CUSTOMER_CODES = [c for c, _ in params.CUSTOMER_FAILURE_CODES]
_CUSTOMER_CUM = list(accumulate(w for _, w in params.CUSTOMER_FAILURE_CODES))
_PG_CODES = [c for c, _ in params.PG_FAILURE_CODES]
_PG_CUM = list(accumulate(w for _, w in params.PG_FAILURE_CODES))


def choose_pg(rng: SimRandom, attempt_no: int, previous_pg: str | None) -> str:
    """첫 시도는 50/50. 재시도는 30% 확률로 다른 PG로 바꾼다."""
    if attempt_no == 1 or previous_pg is None:
        return rng.random.choice(params.PGS)
    if rng.chance(params.RETRY_SWITCH_PG):
        return next(pg for pg in params.PGS if pg != previous_pg)
    return previous_pg


def failure_probabilities(
    attempt_no: int, pg: str, pg_extra_fail: Mapping[str, float] = NO_EXTRA_FAIL
) -> tuple[float, float]:
    """(고객 원인, PG 원인) 실패 확률. PG 원인은 추가분을 더하고 1을 넘지 않는다."""
    if attempt_no == 1:
        customer, pg_cause = params.FIRST_FAIL_CUSTOMER, params.FIRST_FAIL_PG
    else:
        customer, pg_cause = params.RETRY_FAIL_CUSTOMER, params.RETRY_FAIL_PG
    pg_cause = min(1.0, pg_cause + pg_extra_fail.get(pg, 0.0))
    return min(customer, 1.0 - pg_cause), pg_cause  # 늘어난 만큼 성공이 줄어든다


def customer_failure_code(rng: SimRandom, method: str) -> str:
    if method == "BANK_TRANSFER":
        return params.BANK_TRANSFER_CUSTOMER_CODE
    return rng.weighted_choice(_CUSTOMER_CODES, _CUSTOMER_CUM)


def decide_attempt(
    rng: SimRandom,
    attempt_no: int,
    method: str,
    pg: str,
    amount: int,
    requested_at: datetime,
    pg_extra_fail: Mapping[str, float] = NO_EXTRA_FAIL,
) -> AttemptResult:
    """결제 시도 한 번의 결과와 완료 시각."""
    if not 1 <= attempt_no <= params.MAX_ATTEMPTS:
        raise ValueError("시도 번호가 범위를 벗어났습니다.")
    if amount <= 0:
        raise ValueError("결제 금액은 0보다 커야 합니다.")
    customer, pg_cause = failure_probabilities(attempt_no, pg, pg_extra_fail)
    u = rng.random.random()
    if u < pg_cause:
        status, code = FAILED, rng.weighted_choice(_PG_CODES, _PG_CUM)
    elif u < pg_cause + customer:
        status, code = FAILED, customer_failure_code(rng, method)
    else:
        status, code = SUCCESS, None
    completed_at = after(rng, requested_at, params.ATTEMPT_DURATION_SECONDS)
    return AttemptResult(pg, status, code, requested_at, completed_at)


def should_retry(rng: SimRandom, attempt_no: int) -> bool:
    """실패한 attempt_no 다음에 다시 시도할까. 한 주문의 시도는 최대 3번이다."""
    return attempt_no < params.MAX_ATTEMPTS and rng.chance(params.RETRY_RATE)


def next_transition(rng: SimRandom, state: str, at: datetime) -> Transition | None:
    """state가 된 시각 at에서 이어질 다음 전이. 분기는 그 상태가 될 때 한 번만 추첨한다."""
    if state == PAID:
        if rng.chance(params.PAID_CANCEL_RATE):
            return Transition(
                CANCELLED, params.CANCEL_REASON, after(rng, at, params.PAID_CANCEL_SECONDS)
            )
        return Transition(SHIPPED, None, after(rng, at, params.SHIP_SECONDS))
    if state == SHIPPED:
        return Transition(DELIVERED, None, after(rng, at, params.DELIVER_SECONDS))
    if state == DELIVERED:
        if rng.chance(params.REFUND_RATE):
            return Transition(REFUNDED, params.REFUND_REASON, after(rng, at, params.REFUND_SECONDS))
        return None
    return None  # 종결 상태(CANCELLED, PAYMENT_FAILED, REFUNDED)와 PLACED 뒤에는 없다
