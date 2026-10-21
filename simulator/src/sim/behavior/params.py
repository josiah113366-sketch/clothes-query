"""쇼핑 행동(방문·주문·결제·상태 전이)에 쓰는 수치. 값은 이 파일 한 곳에만 둔다.

출처: [설계] 설계 결정, [H&M] H&M 실측, [가정] 팀과 맞추는 임시값.
범위 (a, b)는 양끝을 포함하는 균등 분포다. 시간은 모두 시뮬레이터 초다.
"""

# --- 방문 ---
NORMAL_DAILY_VISITS = 111_000  # [가정] 주문 5,000 ÷ 전환율 4.5%
VIEW_EXTRA_MEAN = 4.0  # [가정] 조회 수 = clamp(1 + round(expovariate(1/4)), 1, 20), 평균 약 5
VIEW_COUNT_MIN = 1
VIEW_COUNT_MAX = 20
CART_RATE = 0.15  # [가정] 방문 → 담기
CART_TO_ORDER_RATE = 0.28  # [가정] 담기 → 주문
DIRECT_ORDER_RATE = 0.003  # [가정] 담기 없이 바로 주문 (전체 방문 대비)
CART_ONLY_ITEMS = (1, 3)  # [가정] 담기만 하고 나간 방문의 담은 개수
TOP_MEMBER_SHARE = 0.2  # [가정] 상위 성향 회원 비율
TOP_MEMBER_WEIGHT = 6  # [가정] 상위 회원의 방문 가중치 (나머지 = 1). 방문의 약 60%

# --- 주문 구성 ---
# [H&M] 주문당 상품 줄 수: (확률, 최소, 최대). 구간 안은 균등
LINE_COUNT_BUCKETS: tuple[tuple[float, int, int], ...] = (
    (0.298, 1, 1),
    (0.235, 2, 2),
    (0.241, 3, 4),
    (0.171, 5, 9),
    (0.055, 10, 15),
)
# [H&M] 해석값 + [가정] 줄당 수량 ("5개 이상"은 5)
QUANTITY_WEIGHTS: tuple[tuple[int, float], ...] = (
    (1, 0.906),
    (2, 0.065),
    (3, 0.018),
    (4, 0.007),
    (5, 0.004),
)
# [가정] 결제 수단. 주문당 한 번 뽑고 재시도에도 그대로다
METHOD_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("CARD", 0.55),
    ("SIMPLE_PAY", 0.35),
    ("BANK_TRANSFER", 0.10),
)

# --- 상품 선택 ---
# [H&M] 구매 쏠림: (순위 비율, 누적 구매 비율). 구간 선형, 역함수로 추첨한다
PURCHASE_CURVE: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (0.01, 0.186),
    (0.05, 0.44),
    (0.10, 0.607),
    (0.20, 0.791),
    (0.50, 0.968),
    (1.0, 1.0),
)
VIEW_FROM_VIEW_RANKING = 0.7  # [가정] 조회 상품의 70%는 조회 순위, 30%는 구매 순위

# --- 방문 안의 시각 [가정] ---
VIEW_GAP_SECONDS = (10, 60)
CART_AFTER_VIEW_SECONDS = (5, 30)
ORDER_AFTER_LAST_EVENT_SECONDS = (20, 120)

# --- 결제 [가정] ---
PGS: tuple[str, ...] = ("PG_A", "PG_B")
FIRST_ATTEMPT_DELAY_SECONDS = (3, 30)  # PLACED → 첫 결제 시도
ATTEMPT_DURATION_SECONDS = (2, 5)  # requested_at → completed_at
FIRST_FAIL_CUSTOMER = 0.07  # 첫 시도: 성공 92%, 실패 8% (고객 7 / PG 1)
FIRST_FAIL_PG = 0.01
RETRY_FAIL_CUSTOMER = 0.2625  # 재시도: 성공 70%, 실패 30% (고객 7 : PG 1 유지)
RETRY_FAIL_PG = 0.0375
RETRY_RATE = 0.6  # 실패 후 재시도할 확률
MAX_ATTEMPTS = 3  # 첫 시도 포함
RETRY_GAP_SECONDS = (30, 120)  # 이전 시도 completed_at 뒤
RETRY_SWITCH_PG = 0.3  # 재시도 때 다른 PG로 바꿀 확률
CUSTOMER_FAILURE_CODES: tuple[tuple[str, float], ...] = (
    ("INSUFFICIENT_BALANCE", 0.40),
    ("CARD_LIMIT_EXCEEDED", 0.35),
    ("CARD_DECLINED", 0.25),
)
BANK_TRANSFER_CUSTOMER_CODE = "INSUFFICIENT_BALANCE"  # 계좌이체의 고객 원인은 항상 이것
PG_FAILURE_CODES: tuple[tuple[str, float], ...] = (
    ("PG_TIMEOUT", 0.60),
    ("PG_ERROR", 0.40),
)

# --- 상태 전이 [가정] ---
PRE_PAYMENT_CANCEL_RATE = 0.015  # 주문 생성 때 추첨
PRE_PAYMENT_CANCEL_SECONDS = (60, 300)
PAID_CANCEL_RATE = 0.03
PAID_CANCEL_SECONDS = (600, 3 * 3600)
SHIP_SECONDS = (2 * 3600, 6 * 3600)
DELIVER_SECONDS = (16 * 3600, 22 * 3600)
REFUND_RATE = 0.07
REFUND_SECONDS = (2 * 3600, 36 * 3600)  # 3일 실행에서 보이도록 압축한 값
CANCEL_REASON = "USER_REQUEST"
REFUND_REASON = "RETURN"

# --- 실행 ---
SECONDS_PER_DAY = 86_400
DEFAULT_SPEED = 1
DEFAULT_SEED = 42
CONTROL_POLL_SECONDS = 1.0  # 제어 신호 확인 주기 (실제 시간)
PROGRESS_SECONDS = 10  # 진행 출력 주기 (실제 시간)
POOL_REFRESH_SECONDS = 60  # 회원 풀 다시 읽기 주기 (실제 시간)
RECONNECT_MAX_WAIT_SECONDS = 30  # 재연결 대기 한계 (1, 2, 4, ... 초)
DEFAULT_CLICK_FILE = ".local/clicks.jsonl"
