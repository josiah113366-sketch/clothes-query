import pytest

from sim.controller import pollution
from sim.controller.model import DUPLICATE_SUCCESS_PAYMENT, ORDER_TOTAL_MISMATCH
from sim.controller.pollution import (
    MemoryPollution,
    PollutionError,
    _unique_success_rows,
    pollution_payment_id,
)


def test_payment_id_is_deterministic() -> None:
    a = pollution_payment_id(42, "inc-1", "order-1")
    assert a == pollution_payment_id(42, "inc-1", "order-1")
    assert a != pollution_payment_id(42, "inc-2", "order-1")
    assert a != pollution_payment_id(42, "inc-1", "order-2")


def test_sql_uses_bound_parameters_only() -> None:
    for statement in (
        pollution.TOTAL_TARGETS,
        pollution.SUCCESS_TARGETS,
        pollution.TOTAL_UPDATE,
        pollution.PAYMENT_INSERT,
    ):
        assert "%s" in statement
        assert "{" not in statement  # 문자열 이어붙이기 없음
    assert "ALTER" not in pollution.TOTAL_UPDATE.upper()


def test_unique_success_rows_keeps_one_row_per_order() -> None:
    rows = [("a", 1), ("a", 2), ("b", 1), ("c", 1)]
    assert _unique_success_rows(rows, 2) == [("a", 1), ("b", 1)]
    assert _unique_success_rows(rows, 10) == [("a", 1), ("b", 1), ("c", 1)]


def test_memory_pollution_and_bad_kind() -> None:
    memory = MemoryPollution(available=5)
    assert memory.check(ORDER_TOTAL_MISMATCH, 30) == 5
    result = memory.apply(DUPLICATE_SUCCESS_PAYMENT, 3, "inc")
    assert result.affected_count == len(result.order_ids) == 3
    with pytest.raises(PollutionError):
        memory.check("DROP_TABLE", 1)
    with pytest.raises(PollutionError):
        MemoryPollution(available=0).check(ORDER_TOTAL_MISMATCH, 1)
