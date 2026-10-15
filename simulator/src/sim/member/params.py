"""회원 베이스라인에 쓰는 설계 수치. 값은 이 파일 한 곳에만 둔다."""

from datetime import datetime, timedelta, timezone

# 고정 오프셋 (+09:00). zoneinfo는 slim 이미지에 tzdata가 없을 수 있어 쓰지 않는다.
KST = timezone(timedelta(hours=9))

# 가입 시각 구간: [시작, 끝). 구간 전체에서 초 단위로 균등 추출한다.
SIGNUP_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=KST)
SIGNUP_END = datetime(2026, 10, 1, 0, 0, 0, tzinfo=KST)
SIGNUP_DAYS = 61

# 나이대 (H&M 회원 수 가중치, 합계로 나눠 확률로 쓴다)
AGE_BANDS: tuple[str, ...] = ("~19", "20s", "30s", "40s", "50s", "60s", "70+")
AGE_BAND_WEIGHTS: dict[str, int] = {
    "~19": 71_583,
    "20s": 528_358,
    "30s": 234_068,
    "40s": 204_118,
    "50s": 226_242,
    "60s": 72_623,
    "70+": 19_127,
}
# 나이대 → 나이 범위 (양끝 포함)
AGE_RANGES: dict[str, tuple[int, int]] = {
    "~19": (16, 19),
    "20s": (20, 29),
    "30s": (30, 39),
    "40s": (40, 49),
    "50s": (50, 59),
    "60s": (60, 69),
    "70+": (70, 99),
}
MIN_AGE = 16

# 비율 (H&M 근거 없는 우리의 가정)
FEMALE_RATIO = 0.55
APP_CHANNEL_RATIO = 0.50
MARKETING_CONSENT_RATIO = 0.70

# 지역 파일
REGION_ROW_COUNT = 256
REGION_COLUMNS: tuple[str, ...] = ("region_sigungu", "sido", "population", "weight")
REGION_WEIGHT_TOLERANCE = 1e-6

# 가짜 비밀번호 해시: "$2b$12$" + 53자 = 60자
PASSWORD_HASH_PREFIX = "$2b$12$"
PASSWORD_HASH_BODY_LENGTH = 53
PASSWORD_HASH_ALPHABET = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

# 전화번호: 010-XXXX-XXXX (8자리 0~99,999,999)
PHONE_SPACE = 10**8

# 적재
DEFAULT_COUNT = 100_000
DEFAULT_SEED = 42
DEFAULT_BATCH_SIZE = 5_000
MIN_BATCH_SIZE = 1_000
MAX_BATCH_SIZE = 5_000
PROGRESS_EVERY = 10_000

# verify: 허용 범위 = 기대 비율 ± SIGMA_LIMIT·σ
SIGMA_LIMIT = 5.0

EMAIL_DOMAIN = "example.com"

# live(신규 가입): 값은 모두 바꿀 수 있는 파라미터다
NORMAL_DAILY_SIGNUPS = 5000  # 평상시 하루 평균 (설계 제안 1,000~2,000에서 올림)
SURGE_MULTIPLIER = 4.6  # 폭주 모드일 때 평상시 대비 배율
DEFAULT_SPEED = 1  # 시간 배속 (1 = 실시간)
BASELINE_END = SIGNUP_END  # 이 시각 이후의 가입이 신규 가입이다
CONTROL_POLL_SECONDS = 1.0  # 제어 신호 확인 주기 (실제 시간)
PHONE_RETRY_LIMIT = 10  # 전화번호 중복 시 새 번호로 다시 시도하는 최대 횟수
RECONNECT_MAX_WAIT_SECONDS = 30  # 재연결 대기 한계 (1, 2, 4, ... 초로 늘다가 여기서 멈춤)
LIVE_PROGRESS_SECONDS = 10  # 진행 출력 주기 (실제 시간)
SECONDS_PER_DAY = 86_400
