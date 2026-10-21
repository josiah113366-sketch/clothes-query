"""데이터 오염: DB 제약(CHECK, UNIQUE, FK)은 통과하지만 업무 규칙은 어기는 행을 만든다.

스키마 변경(ALTER TABLE)은 하지 않는다. 한 종류의 오염은 한 트랜잭션이다.
오류 메시지는 common.db의 오류 가리기를 거친다 (호스트, 비밀번호, 행 내용 없음).
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from sim.common.db import connect, safe_db_errors
from sim.common.rng import SimRandom, derive_seed
from sim.controller.model import (
    DUPLICATE_SUCCESS_PAYMENT,
    ORDER_TOTAL_MISMATCH,
    POLLUTION_KINDS,
    TOTAL_MISMATCH_DELTA,
)

# 대상: 결제가 끝난(PAID 이후) 최근 주문 / SUCCESS 결제가 있는 최근 주문
TOTAL_TARGETS = """
    SELECT order_id FROM orders
    WHERE status IN ('PAID', 'SHIPPED', 'DELIVERED')
    ORDER BY ordered_at DESC, order_id
    LIMIT %s
"""
SUCCESS_TARGETS = """
    SELECT o.order_id, p.method, p.pg, p.amount, p.completed_at,
           (SELECT max(q.attempt_no) FROM payments q WHERE q.order_id = o.order_id)
    FROM orders o
    JOIN payments p ON p.order_id = o.order_id AND p.status = 'SUCCESS'
    ORDER BY o.ordered_at DESC, o.order_id, p.attempt_no
    LIMIT %s
"""
TOTAL_UPDATE = "UPDATE orders SET total_amount = total_amount + %s WHERE order_id = ANY(%s)"
PAYMENT_INSERT = """
    INSERT INTO payments (payment_id, order_id, attempt_no, method, pg, amount, status,
                          failure_code, requested_at, completed_at)
    VALUES (%s, %s, %s, %s, %s, %s, 'SUCCESS', NULL, %s, %s)
"""


class PollutionError(RuntimeError):
    """오염을 만들 수 없다 (대상 없음, 잘못된 종류). 메시지에 행 내용을 싣지 않는다."""


@dataclass(frozen=True)
class PollutionResult:
    kind: str
    affected_count: int
    order_ids: tuple[str, ...] = field(default_factory=tuple)


class PollutionExecutor(Protocol):
    def check(self, kind: str, count: int) -> int:
        """읽기만 해서 대상 수(최대 count)를 센다. 대상이 없으면 PollutionError."""
        ...

    def apply(self, kind: str, count: int, incident_id: str) -> PollutionResult: ...


def pollution_payment_id(seed: int, incident_id: str, order_id: str) -> str:
    return SimRandom(derive_seed(seed, "pollution", incident_id, order_id)).uuid4()


def _check_kind(kind: str) -> None:
    if kind not in POLLUTION_KINDS:
        raise PollutionError(f"오염 종류는 {', '.join(POLLUTION_KINDS)} 중 하나여야 합니다.")


def _unique_success_rows(rows: list[tuple], count: int) -> list[tuple]:
    """주문당 SUCCESS 결제 한 행만 (이미 오염돼 둘 이상이면 첫 행)."""
    seen: set[str] = set()
    out: list[tuple] = []
    for row in rows:
        order_id = str(row[0])
        if order_id not in seen:
            seen.add(order_id)
            out.append(row)
        if len(out) == count:
            break
    return out


class DbPollution:
    def __init__(self, database_url: str, seed: int, schema: str | None = None) -> None:
        self._url, self._seed, self._schema = database_url, seed, schema

    def check(self, kind: str, count: int) -> int:
        _check_kind(kind)
        with connect(self._url, self._schema) as conn, safe_db_errors():
            conn.read_only = True
            found = self._targets(conn, kind, count)
        if not found:
            raise PollutionError("오염할 대상 주문이 없습니다. 주문이 쌓인 뒤 다시 시도하세요.")
        return len(found)

    def _targets(self, conn, kind: str, count: int) -> list[tuple]:
        if kind == ORDER_TOTAL_MISMATCH:
            return conn.execute(TOTAL_TARGETS, (count,)).fetchall()
        assert kind == DUPLICATE_SUCCESS_PAYMENT
        # 한 주문에 SUCCESS가 이미 여럿일 수 있어 넉넉히 읽고 주문 단위로 줄인다
        return _unique_success_rows(conn.execute(SUCCESS_TARGETS, (count * 4,)).fetchall(), count)

    def apply(self, kind: str, count: int, incident_id: str) -> PollutionResult:
        _check_kind(kind)
        with connect(self._url, self._schema) as conn, safe_db_errors():  # 끝에 커밋, 오류면 롤백
            targets = self._targets(conn, kind, count)
            if not targets:
                raise PollutionError("오염할 대상 주문이 없습니다.")
            order_ids = [str(row[0]) for row in targets]
            if kind == ORDER_TOTAL_MISMATCH:
                conn.execute(TOTAL_UPDATE, (TOTAL_MISMATCH_DELTA, order_ids))
            else:
                with conn.cursor() as cur:
                    cur.executemany(
                        PAYMENT_INSERT, [self._duplicate(row, incident_id) for row in targets]
                    )
        return PollutionResult(kind, len(order_ids), tuple(order_ids))

    def _duplicate(self, row: tuple, incident_id: str) -> tuple:
        order_id, method, pg, amount, completed_at, max_attempt = row
        order_id = str(order_id)
        return (
            pollution_payment_id(self._seed, incident_id, order_id),
            order_id,
            max_attempt + 1,
            method,
            pg,
            amount,
            completed_at + timedelta(seconds=1),
            completed_at + timedelta(seconds=2),
        )


class MemoryPollution:
    """테스트용. available은 종류별 대상 수다."""

    def __init__(self, available: int = 1_000) -> None:
        self.available = available
        self.applied: list[tuple[str, int, str]] = []
        self.fail_apply = False

    def check(self, kind: str, count: int) -> int:
        _check_kind(kind)
        if self.available <= 0:
            raise PollutionError("오염할 대상 주문이 없습니다.")
        return min(count, self.available)

    def apply(self, kind: str, count: int, incident_id: str) -> PollutionResult:
        _check_kind(kind)
        if self.fail_apply:
            raise PollutionError("오염 적용 실패 (테스트)")
        n = min(count, self.available)
        self.applied.append((kind, count, incident_id))
        return PollutionResult(kind, n, tuple(f"order-{i:04d}" for i in range(n)))
