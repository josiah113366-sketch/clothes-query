"""신규 가입 도착 간격. 푸아송 과정이므로 간격은 지수분포다.

속도는 common.curve의 곡선과 모드를 따른다. 시간대 경계에서 계단으로 바뀌며,
간격은 뽑은 시점의 속도로 뽑는다 (경계에서 생기는 작은 오차는 허용한다).
"""

from datetime import datetime

from sim.common.curve import rate_factor
from sim.common.rng import SimRandom
from sim.member import params


def signups_per_second(daily: float, mode: str, sim_time: datetime) -> float:
    """λ = 하루 평균 가입 수 × rate_factor(모드, 시각) ÷ 86,400."""
    return daily * rate_factor(mode, sim_time) / params.SECONDS_PER_DAY


def next_interval(rng: SimRandom, daily: float, mode: str, sim_time: datetime) -> float:
    """다음 가입까지의 간격 (시뮬레이터 초)."""
    rate = signups_per_second(daily, mode, sim_time)
    if rate <= 0:
        raise ValueError("가입 속도는 0보다 커야 합니다.")
    return rng.random.expovariate(rate)
