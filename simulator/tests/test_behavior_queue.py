from datetime import datetime, timedelta

import pytest

from sim.behavior.model import ClickEvent, ClickTask
from sim.behavior.queue import ScheduledQueue
from sim.common.timezone import KST

T0 = datetime(2026, 10, 12, 9, 0, 0, tzinfo=KST)


def _task(name: str) -> ClickTask:
    return ClickTask(ClickEvent(name, "view", "m", "a", T0, "s"))


def test_pops_in_due_then_registration_order() -> None:
    q = ScheduledQueue()
    q.push(T0 + timedelta(seconds=5), _task("late"))
    q.push(T0, _task("first"))
    q.push(T0, _task("second"))
    assert q.peek_due() == T0 and len(q) == 3
    assert [q.pop().task.event.event_id for _ in range(3)] == ["first", "second", "late"]
    assert q.peek_due() is None and len(q) == 0


def test_push_front_restores_position() -> None:
    q = ScheduledQueue()
    q.push(T0, _task("a"))
    q.push(T0, _task("b"))
    entry = q.pop()
    q.push(T0, _task("c"))
    q.push_front(entry)
    assert [q.pop().task.event.event_id for _ in range(3)] == ["a", "b", "c"]


def test_naive_due_is_rejected() -> None:
    with pytest.raises(ValueError):
        ScheduledQueue().push(datetime(2026, 10, 12), _task("x"))
