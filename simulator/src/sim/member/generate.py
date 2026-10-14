"""회원 생성 순수 함수. DB, 네트워크, 현재 시각을 부르지 않는다."""

from datetime import date, datetime, timedelta
from itertools import accumulate

from sim.common.regions import RegionTable
from sim.common.rng import SimRandom
from sim.member import params
from sim.member.model import NewMember

_AGE_CUM_WEIGHTS = tuple(accumulate(params.AGE_BAND_WEIGHTS[band] for band in params.AGE_BANDS))
_SIGNUP_SECONDS = int((params.SIGNUP_END - params.SIGNUP_START).total_seconds())


def age_band_of(age: int) -> str:
    """나이를 나이대로 바꾼다."""
    if age < params.MIN_AGE:
        raise ValueError(f"나이가 최소 나이({params.MIN_AGE}) 미만입니다.")
    for band in params.AGE_BANDS:
        low, high = params.AGE_RANGES[band]
        if low <= age <= high:
            return band
    raise ValueError("나이대를 찾을 수 없습니다.")


def random_signup_at(rng: SimRandom) -> datetime:
    """가입 구간 전체에서 초 단위로 균등하게 한 시각을 뽑는다."""
    return params.SIGNUP_START + timedelta(seconds=rng.randrange(_SIGNUP_SECONDS))


def format_phone(number: int) -> str:
    """0~99,999,999를 010-XXXX-XXXX로 바꾼다. 베이스라인과 신규 가입이 같은 형식을 쓴다."""
    return f"010-{number // 10_000:04d}-{number % 10_000:04d}"


def draw_phone(rng: SimRandom) -> str:
    """무작위 전화번호 하나. 다른 회원과 겹치는지는 확인하지 않는다 (DB UNIQUE가 막는다)."""
    return format_phone(rng.randrange(params.PHONE_SPACE))


def allocate_phones(rng: SimRandom, count: int) -> list[str]:
    """중복 없는 010 번호 count개."""
    if not 0 <= count <= params.PHONE_SPACE:
        raise ValueError("전화번호를 배정할 수 없는 인원입니다.")
    numbers = rng.random.sample(range(params.PHONE_SPACE), count)
    return [format_phone(n) for n in numbers]


def _random_birth_date(rng: SimRandom, year: int) -> date:
    """그 연도에 실제로 있는 날짜 중 하루를 균등하게 뽑는다."""
    first = date(year, 1, 1)
    days_in_year = (date(year + 1, 1, 1) - first).days
    return first + timedelta(days=rng.randrange(days_in_year))


def generate_member(
    rng: SimRandom, signup_at: datetime, regions: RegionTable, phone: str
) -> NewMember:
    if signup_at.tzinfo is None or signup_at.utcoffset() is None:
        raise ValueError("signup_at은 시간대 정보가 있는 값이어야 합니다.")

    member_id = rng.uuid4()
    gender = "F" if rng.chance(params.FEMALE_RATIO) else "M"
    name = rng.name(gender)

    band = rng.weighted_choice(params.AGE_BANDS, _AGE_CUM_WEIGHTS)
    low, high = params.AGE_RANGES[band]
    age = rng.randint(low, high)
    signup_year = signup_at.astimezone(params.KST).year
    birth_date = _random_birth_date(rng, signup_year - age)

    channel = "app" if rng.chance(params.APP_CHANNEL_RATIO) else "web"
    consent = rng.chance(params.MARKETING_CONSENT_RATIO)
    password_hash = params.PASSWORD_HASH_PREFIX + rng.random_string(
        params.PASSWORD_HASH_ALPHABET, params.PASSWORD_HASH_BODY_LENGTH
    )
    region = rng.weighted_choice(regions.names, regions.cum_weights)

    return NewMember(
        member_id=member_id,
        name=name,
        email=f"user_{member_id.replace('-', '')}@{params.EMAIL_DOMAIN}",
        phone=phone,
        birth_date=birth_date,
        password_hash=password_hash,
        gender=gender,
        signup_at=signup_at,
        signup_channel=channel,
        marketing_consent=consent,
        status="ACTIVE",
        withdrawn_at=None,
        region_sigungu=region,
        age_band=age_band_of(signup_year - birth_date.year),
    )
