"""시뮬레이터 시계. 현재 시각과 대기를 주입할 수 있어 테스트에서 가짜 시계로 바꿔 쓴다."""

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from sim.common.timezone import KST


def _real_now() -> datetime:
    return datetime.now(KST)


class FakeTime:
    """가짜 시간 원천. sleep하면 시간이 그만큼 흐른다 (실제로는 기다리지 않는다)."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("start는 시간대 정보가 있는 값이어야 합니다.")
        self.current = start

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class SimClock:
    """시뮬레이터 시각 = 시작 시각 + 배속 × 실제 경과 시간. 항상 KST(+09:00)로 돌려준다."""

    def __init__(
        self,
        speed: float = 1.0,
        now: Callable[[], datetime] = _real_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if speed <= 0:
            raise ValueError("배속은 0보다 커야 합니다.")
        self.speed = speed
        self._now = now
        self._sleep = sleep
        self._start = now()

    @classmethod
    def fake(cls, fake_time: FakeTime, speed: float = 1.0) -> "SimClock":
        return cls(speed, fake_time.now, fake_time.sleep)

    def restart(self) -> None:
        """기준 시각을 지금으로 다시 잡는다. 준비(연결, 초기화)에 든 시간을 실행 시간에서 뺀다."""
        self._start = self._now()

    def real_elapsed(self) -> float:
        """시작한 뒤 실제로 흐른 초."""
        return (self._now() - self._start).total_seconds()

    def now(self) -> datetime:
        """시뮬레이터 시각 (시간대 정보가 있는 KST)."""
        return (self._start + timedelta(seconds=self.speed * self.real_elapsed())).astimezone(KST)

    def sleep(self, real_seconds: float) -> None:
        """실제 시간으로 real_seconds 대기한다."""
        if real_seconds > 0:
            self._sleep(real_seconds)
