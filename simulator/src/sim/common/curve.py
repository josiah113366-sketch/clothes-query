"""요일·시간대 곡선과 모드별 속도 배율. 가입(member)과 방문(behavior)이 같이 쓴다.

값은 모두 "하루 평균 속도 대비 배율"이다. 속도(초당) = 하루 건수 ÷ 86,400 × rate_factor.
순수 함수만 둔다. 난수, DB, 현재 시각을 안에서 부르지 않는다.
"""

from datetime import datetime

from sim.common.timezone import KST

# 요일별 비율 (H&M 거래의 요일 비율, 월~일). 합 = 1
WEEKDAY_RATIO: tuple[float, ...] = (0.128, 0.132, 0.152, 0.153, 0.149, 0.159, 0.127)

# 시간대별 비율 (KST, [시작시, 끝시)). H&M에 시간 정보가 없어 우리가 정한 가정이다. 합 = 1
HOUR_SHARE: tuple[tuple[int, int, float], ...] = (
    (0, 6, 0.05),
    (6, 9, 0.08),
    (9, 12, 0.14),
    (12, 14, 0.11),
    (14, 18, 0.17),
    (18, 22, 0.30),
    (22, 24, 0.15),
)

# medium/burst는 일상 피크 시간대 속도의 몇 배인가. 시간대·요일과 무관하게 고정이다
MODE_PEAK_MULTIPLE: dict[str, float] = {"medium": 3.0, "burst": 10.0}

HOURS_PER_DAY = 24
SUM_TOLERANCE = 1e-9


def _segment_factor(start: int, end: int, share: float) -> float:
    """구간 비율 ÷ (구간 시간 ÷ 24). 구간 안에서는 일정하다 (계단 함수)."""
    return share / ((end - start) / HOURS_PER_DAY)


def validate() -> None:
    """곡선 표가 올바른지 확인한다. 어긋나면 ValueError."""
    if len(WEEKDAY_RATIO) != 7:
        raise ValueError("요일 비율은 7개여야 합니다.")
    if abs(sum(WEEKDAY_RATIO) - 1) > SUM_TOLERANCE:
        raise ValueError("요일 비율의 합이 1이 아닙니다.")
    if abs(sum(share for _, _, share in HOUR_SHARE) - 1) > SUM_TOLERANCE:
        raise ValueError("시간대 비율의 합이 1이 아닙니다.")
    expected_start = 0
    for start, end, _ in HOUR_SHARE:
        if start != expected_start or end <= start:
            raise ValueError("시간대 구간이 0~24시를 빈틈·겹침 없이 덮지 않습니다.")
        expected_start = end
    if expected_start != HOURS_PER_DAY:
        raise ValueError("시간대 구간이 24시에서 끝나지 않습니다.")


validate()

PEAK_HOUR_FACTOR: float = max(_segment_factor(*segment) for segment in HOUR_SHARE)


def _to_kst(sim_time: datetime) -> datetime:
    if sim_time.tzinfo is None:
        raise ValueError("sim_time은 시간대 정보가 있는 값이어야 합니다.")
    return sim_time.astimezone(KST)


def weekday_factor(sim_time: datetime) -> float:
    """요일 배율 = 7 × 요일 비율 (날짜 경계는 KST 00:00)."""
    return 7 * WEEKDAY_RATIO[_to_kst(sim_time).weekday()]


def hour_factor(sim_time: datetime) -> float:
    """시간대 배율 (KST 시각이 속한 구간의 값)."""
    hour = _to_kst(sim_time).hour
    for start, end, share in HOUR_SHARE:
        if start <= hour < end:
            return _segment_factor(start, end, share)
    raise AssertionError("validate()가 구간이 0~24시를 덮는다고 확인했다")


def rate_factor(mode: str, sim_time: datetime) -> float:
    """평균 속도 대비 배율. normal은 요일×시간대, medium/burst는 피크 대비 고정 배수다."""
    if mode == "normal":
        return weekday_factor(sim_time) * hour_factor(sim_time)
    if mode in MODE_PEAK_MULTIPLE:
        _to_kst(sim_time)  # 시간대 정보는 모드와 상관없이 같은 규칙으로 확인한다
        return PEAK_HOUR_FACTOR * MODE_PEAK_MULTIPLE[mode]
    raise ValueError(f"알 수 없는 모드입니다: {mode}")
