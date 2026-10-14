"""신규 가입 도착 간격. 푸아송 과정이므로 간격은 지수분포다."""

from datetime import datetime

from sim.common.rng import SimRandom
from sim.member import params


def rate_multiplier(sim_time: datetime) -> float:
    """시각에 따른 속도 배율. 지금은 균등(항상 1.0)이다.

    하루 안의 분포나 날짜별 곡선은 설계에서 미정이라, 정해지면 이 함수만 바꾼다.
    """
    return 1.0


def mode_multiplier(mode: str, surge_multiplier: float) -> float:
    if mode == "normal":
        return 1.0
    if mode == "surge":
        return surge_multiplier
    raise ValueError(f"알 수 없는 모드입니다: {mode}")


def signups_per_second(
    daily: float, mode: str, surge_multiplier: float, sim_time: datetime
) -> float:
    """λ = 하루 가입 수 × 모드 배율 × rate_multiplier(시각) ÷ 86,400."""
    return (
        daily
        * mode_multiplier(mode, surge_multiplier)
        * rate_multiplier(sim_time)
        / params.SECONDS_PER_DAY
    )


def next_interval(
    rng: SimRandom, daily: float, mode: str, surge_multiplier: float, sim_time: datetime
) -> float:
    """다음 가입까지의 간격 (시뮬레이터 초)."""
    rate = signups_per_second(daily, mode, surge_multiplier, sim_time)
    if rate <= 0:
        raise ValueError("가입 속도는 0보다 커야 합니다.")
    return rng.random.expovariate(rate)
