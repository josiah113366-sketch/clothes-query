"""예약 큐. (예정 시각, 등록 순번) 순서로 꺼낸다. 메모리에만 있다 (재시작하면 사라진다)."""

import heapq
from datetime import datetime
from typing import NamedTuple

from sim.behavior.model import Task


class Entry(NamedTuple):
    due: datetime
    seq: int  # 같은 시각이면 먼저 등록한 것부터
    task: Task


class ScheduledQueue:
    def __init__(self) -> None:
        self._heap: list[Entry] = []
        self._seq = 0

    def push(self, due: datetime, task: Task) -> Entry:
        if due.tzinfo is None:
            raise ValueError("due는 시간대 정보가 있는 값이어야 합니다.")
        entry = Entry(due, self._seq, task)
        self._seq += 1
        heapq.heappush(self._heap, entry)
        return entry

    def peek_due(self) -> datetime | None:
        return self._heap[0].due if self._heap else None

    def pop(self) -> Entry:
        return heapq.heappop(self._heap)

    def push_front(self, entry: Entry) -> None:
        """실패한 항목을 되돌린다. 원래 (시각, 순번)을 그대로 쓰므로 다시 맨 앞에 온다."""
        heapq.heappush(self._heap, entry)

    def __len__(self) -> int:
        return len(self._heap)
