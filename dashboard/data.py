"""화면에 쓰는 데이터를 가져오는 함수 모음.

지금은 **가짜(더미) 데이터**다. 테이블 이름과 컬럼은 노션 설계 문서를 그대로 따랐다.
  - 「Gold A 설계 정리」 -> order_sales_hourly, product_sales_daily, funnel_session_product,
                           funnel_daily, review_product_daily, review_aspect_daily
  - 「Gold B 칼럼 구성」 -> payment_attempts(뷰), malformed_messages(뷰), malformed_events,
                           bronze_lag_snapshots, reprocess_events
  - gold_b.anomaly 는 탐지 담당이 정의하는 표라서 컬럼은 임시(자리표시)다.
실데이터 연결 때는 **각 함수 본문만** Athena 조회로 바꾸면 되고, 페이지 코드는 그대로 둔다.
  Gold A -> S3 gold_a (Athena),  Gold B -> S3 clothes-query-datalake/gold_b/ (Athena DB `gold_b`)

시간 규칙 (노션 문서 기준)
  - Gold A 날짜/시각은 KST 컬럼(*_kst).
  - Gold B 는 UTC 로 저장한다. 화면에 보여줄 때 to_kst() 로 바꾼다.

※ 더미 값은 임의의 숫자이며 실제 결제/리뷰 데이터가 아니다.
※ 리뷰 원문은 내부용이다. 외부 서비스에 올리거나 Git 에 넣지 않는다.
"""

import functools
import logging
import os

import numpy as np
import pandas as pd
import streamlit as st

# 같은 값이 나오도록 고정한 난수 시드 (새로고침해도 더미 값이 바뀌지 않게)
_SEED = 42
# 캐시 시간(초). 실데이터 연결 시 갱신 주기에 맞춰 조정 (Gold B 는 1분 단위라 더 짧게).
_TTL_A, _TTL_B = 300, 60

# 리뷰 속성 11개 (감성분석 모델 속성 목록과 맞춤)
ASPECTS = [
    "사이즈·핏",
    "품질·내구성",
    "재질·촉감",
    "디자인",
    "색상",
    "가격",
    "배송",
    "포장",
    "CS",
    "세탁·관리",
    "활용성·사용감",
]
# 더미 상품. article_id = 개별 상품, product_code = 같은 디자인 묶음 (노션 '상품 구분 기준')
PRODUCTS = pd.DataFrame(
    {
        "article_id": [
            "0706016001",
            "0706016002",
            "0706016003",
            "0108775015",
            "0108775044",
            "0176209023",
        ],
        "product_code": ["0706016", "0706016", "0706016", "0108775", "0108775", "0176209"],
        "name": [
            "오버핏 니트 블랙",
            "오버핏 니트 베이지",
            "오버핏 니트 그레이",
            "베이직 티셔츠 화이트",
            "베이직 티셔츠 블랙",
            "와이드 데님 인디고",
        ],
    }
)
MODEL_VERSIONS = ["s2c-v1"]  # 분석모델 버전. 서로 다른 버전을 섞어 계산하지 않는다 (노션 규칙)


# ---- 실데이터 연결 + 더미 대체 ----------------------------------------------
# DATA_SOURCE: "auto"(기본) = 실데이터 조회 함수가 등록돼 있으면 먼저 쓰고, 없거나 실패하거나 빈 결과면 더미로 대체.
#              "dummy" = 항상 더미.
DATA_SOURCE = os.getenv("DATA_SOURCE", "auto")
# 실데이터 조회 함수 등록처: {"get_order_sales_hourly": 함수, ...}. 함수 이름은 아래 get_* 와 같게 하고,
# 같은 인자를 받아 같은 컬럼의 DataFrame 을 돌려주면 된다. (Athena 연결 후 여기에 등록. 지금은 비어 있음)
_REAL: dict = {}
# 더미로 대체된 데이터 이름 모음. app.py 가 사이드바에 '더미 사용 중'을 표시하는 데 쓴다.
USING_DUMMY: set = set()
_log = logging.getLogger(__name__)


def dataset(ttl: int):
    """get_* 함수에 붙이는 데코레이터. 캐시(ttl초) + '실데이터 실패/없음 -> 더미' 대체를 한꺼번에 처리한다.
    데코레이터가 붙은 함수 본문은 '더미 생성'이다."""

    def deco(dummy_fn):
        name = dummy_fn.__name__

        @st.cache_data(ttl=ttl)
        @functools.wraps(dummy_fn)
        def wrapper(*args, **kwargs):
            real = _REAL.get(name)
            if DATA_SOURCE != "dummy" and real is not None:
                try:
                    df = real(*args, **kwargs)
                    if df is not None and len(df) > 0:
                        USING_DUMMY.discard(name)
                        return df
                except Exception:  # noqa: BLE001  조회 실패도 화면을 죽이지 않고 더미로 보여준다
                    _log.exception("실데이터 조회 실패, 더미 사용: %s", name)
            USING_DUMMY.add(name)
            return dummy_fn(*args, **kwargs)

        return wrapper

    return deco


def safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """비율 계산. 분모가 0이면 0%가 아니라 NaN(= 계산 불가)으로 둔다 (노션: 'NULL로 표시')."""
    return num / den.where(den != 0)


def to_kst(ts: pd.Series) -> pd.Series:
    """Gold B 의 UTC 시각을 KST 로 바꾼다 (화면 표시용)."""
    return pd.to_datetime(ts, utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)


def _today_kst() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()


# =====================================================================
# Gold A (상품 관리 화면)
# =====================================================================
@dataset(_TTL_A)
def get_order_sales_hourly(days: int = 7) -> pd.DataFrame:
    """KST 1시간 단위 주문·결제. 컬럼: hour_start_kst, order_count, paid_order_count, approved_amount.

    주의: 같은 시간의 paid_order_count ÷ order_count 를 '구매 전환율'로 표시하지 않는다
    (이전 시간에 생성된 주문이 나중에 결제될 수 있음).
    """
    rng = np.random.default_rng(_SEED)
    hours = pd.date_range(end=_today_kst() + pd.Timedelta(hours=9), periods=days * 24, freq="60min")
    orders = rng.integers(20, 60, len(hours))
    paid = (orders * rng.uniform(0.82, 0.95, len(hours))).astype(int)
    paid[-30:-24] = (paid[-30:-24] * 0.4).astype(
        int
    )  # 더미: 결제 성공만 줄어든 구간 (시나리오 A 흉내)
    amount = paid * rng.integers(38_000, 52_000, len(hours))
    return pd.DataFrame(
        {
            "hour_start_kst": hours,
            "order_count": orders,
            "paid_order_count": paid,
            "approved_amount": amount,
        }
    )


@dataset(_TTL_A)
def get_product_sales_daily(days: int = 30) -> pd.DataFrame:
    """결제일(KST) × 상품 판매. 컬럼: sales_date_kst, article_id, product_code, paid_order_count,
    sold_quantity, item_sales_amount.  금액은 취소·환불 차감 전, 주문 당시 unit_price 기준."""
    rng = np.random.default_rng(_SEED + 1)
    dates = pd.date_range(end=_today_kst(), periods=days)
    rows = []
    for _, p in PRODUCTS.iterrows():
        base = rng.integers(8, 30)
        for i, d in enumerate(dates):
            orders = max(
                0,
                int(
                    base
                    + rng.integers(-4, 5)
                    - (i > days - 8) * base * 0.5 * (p.article_id == "0706016001")
                ),
            )
            qty = orders + int(rng.integers(0, 3))
            rows.append(
                (
                    d,
                    p.article_id,
                    p.product_code,
                    orders,
                    qty,
                    qty * int(rng.integers(29, 59)) * 1000,
                )
            )
    return pd.DataFrame(
        rows,
        columns=[
            "sales_date_kst",
            "article_id",
            "product_code",
            "paid_order_count",
            "sold_quantity",
            "item_sales_amount",
        ],
    )


@dataset(_TTL_A)
def get_funnel_daily(days: int = 30) -> pd.DataFrame:
    """첫 조회일(KST) × 상품 구매 퍼널. 컬럼은 노션 funnel_daily 와 동일(방문 수 5종 + 전환율 5종).

    비율은 safe_div 로 계산: 분모 0 이면 NaN. 장바구니 없이 주문하는 방문이 있으므로
    cart_sessions - order_sessions 를 이탈 수로 쓰지 않는다 (담기 후 이탈 = cart_sessions - cart_order_sessions).
    """
    rng = np.random.default_rng(_SEED + 2)
    dates = pd.date_range(end=_today_kst(), periods=days)
    rows = []
    for _, p in PRODUCTS.iterrows():
        for d in dates:
            view = int(rng.integers(150, 600))
            cart = int(view * rng.uniform(0.10, 0.22))
            cart_order = int(cart * rng.uniform(0.35, 0.6))
            order = cart_order + int(
                view * rng.uniform(0.005, 0.02)
            )  # 장바구니 없이 바로 주문한 방문 포함
            paid = int(order * rng.uniform(0.85, 0.97))
            rows.append((d, p.article_id, p.product_code, view, cart, order, paid, cart_order))
    df = pd.DataFrame(
        rows,
        columns=[
            "funnel_date_kst",
            "article_id",
            "product_code",
            "view_sessions",
            "cart_sessions",
            "order_sessions",
            "paid_sessions",
            "cart_order_sessions",
        ],
    )
    df["view_to_cart_rate"] = safe_div(df.cart_sessions, df.view_sessions)
    df["view_to_order_rate"] = safe_div(df.order_sessions, df.view_sessions)
    df["view_to_paid_rate"] = safe_div(df.paid_sessions, df.view_sessions)
    df["cart_to_order_rate"] = safe_div(df.cart_order_sessions, df.cart_sessions)
    df["order_to_paid_rate"] = safe_div(df.paid_sessions, df.order_sessions)
    return df


@dataset(_TTL_A)
def get_funnel_session_product(article_id: str, n: int = 15) -> pd.DataFrame:
    """방문 × 상품 단계 도달 상세(전환율의 근거). 컬럼: session_id, article_id, first_view_at_kst,
    first_cart_at_kst, first_order_at_kst, first_paid_at_kst, has_*, order_ids"""
    rng = np.random.default_rng(_SEED + 3)
    base = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).floor("min")
    rows = []
    for i in range(n):
        view = base - pd.Timedelta(minutes=int(rng.integers(10, 2000)))
        depth = rng.choice([1, 2, 3, 4], p=[0.6, 0.15, 0.1, 0.15])  # 어디까지 도달했나
        cart = view + pd.Timedelta(minutes=3) if depth >= 2 else pd.NaT
        order = view + pd.Timedelta(minutes=8) if depth >= 3 else pd.NaT
        paid = view + pd.Timedelta(minutes=9) if depth >= 4 else pd.NaT
        rows.append(
            (
                f"s-{i:04d}",
                article_id,
                view,
                cart,
                order,
                paid,
                True,
                depth >= 2,
                depth >= 3,
                depth >= 4,
                f"o-{i:04d}" if depth >= 3 else "",
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "session_id",
            "article_id",
            "first_view_at_kst",
            "first_cart_at_kst",
            "first_order_at_kst",
            "first_paid_at_kst",
            "has_view",
            "has_cart",
            "has_order",
            "has_paid",
            "order_ids",
        ],
    )


@dataset(_TTL_A)
def get_review_product_daily(days: int = 30) -> pd.DataFrame:
    """작성일(KST) × 상품 리뷰. 컬럼: review_date_kst, article_id, product_code, review_count,
    rating_sum, average_rating, low_rating_count, low_rating_rate.

    낮은 별점(1~2점)은 별점 기준이며 AI 가 판정한 부정 감성과 다르다.
    기간 평균 별점은 일별 평균의 평균이 아니라 sum(rating_sum) ÷ sum(review_count) 로 다시 계산해야 한다.
    """
    rng = np.random.default_rng(_SEED + 4)
    dates = pd.date_range(end=_today_kst(), periods=days)
    rows = []
    for _, p in PRODUCTS.iterrows():
        for d in dates:
            cnt = int(rng.integers(0, 25))
            rating_sum = int(cnt * rng.uniform(3.4, 4.6))
            low = int(cnt * rng.uniform(0.0, 0.25))
            rows.append((d, p.article_id, p.product_code, cnt, rating_sum, low))
    df = pd.DataFrame(
        rows,
        columns=[
            "review_date_kst",
            "article_id",
            "product_code",
            "review_count",
            "rating_sum",
            "low_rating_count",
        ],
    )
    df["average_rating"] = safe_div(df.rating_sum, df.review_count)
    df["low_rating_rate"] = safe_div(df.low_rating_count, df.review_count)
    return df


@dataset(_TTL_A)
def get_review_aspect_daily(days: int = 30) -> pd.DataFrame:
    """작성일(KST) × 상품 × 속성 × 모델 버전. 컬럼: review_date_kst, article_id, product_code, aspect,
    model_version, mentioned/positive/neutral/negative_review_count, negative_rate.

    주의: 리뷰 하나가 여러 속성을 언급하므로 속성별 리뷰 수를 합쳐 '전체 리뷰 수'로 쓰지 않는다.
    서로 다른 model_version 을 섞어 하나의 비율로 만들지 않는다 (화면에서 버전을 하나 고르게 함).
    """
    rng = np.random.default_rng(_SEED + 5)
    dates = pd.date_range(end=_today_kst(), periods=days)
    rows = []
    for _, p in PRODUCTS.iterrows():
        for d in dates:
            for a in ASPECTS:
                m = int(rng.integers(0, 8))
                neg = int(
                    m * rng.uniform(0, 0.5)
                    + (a == "품질·내구성" and p.article_id == "0706016001" and d > dates[-8]) * 2
                )
                neg = min(neg, m)
                pos = int((m - neg) * rng.uniform(0.4, 0.9))
                rows.append(
                    (
                        d,
                        p.article_id,
                        p.product_code,
                        a,
                        MODEL_VERSIONS[0],
                        m,
                        pos,
                        m - neg - pos,
                        neg,
                    )
                )
    df = pd.DataFrame(
        rows,
        columns=[
            "review_date_kst",
            "article_id",
            "product_code",
            "aspect",
            "model_version",
            "mentioned_review_count",
            "positive_review_count",
            "neutral_review_count",
            "negative_review_count",
        ],
    )
    df["negative_rate"] = safe_div(df.negative_review_count, df.mentioned_review_count)
    return df


@dataset(_TTL_A)
def get_data_status() -> pd.DataFrame:
    """Gold A '데이터 상태' (통합 조회 하단). 처리 완료 범위·갱신 시각·품질 결과.
    불완전한 데이터를 정상 성과로 오해하지 않도록 화면에 함께 보여주는 정보다."""
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).floor("min")
    return pd.DataFrame(
        [
            {
                "dataset": "order_sales_hourly",
                "processed_until_kst": now.floor("60min"),
                "updated_at_kst": now,
                "quality": "정상",
            },
            {
                "dataset": "product_sales_daily",
                "processed_until_kst": _today_kst(),
                "updated_at_kst": now,
                "quality": "정상",
            },
            {
                "dataset": "funnel_daily",
                "processed_until_kst": _today_kst() - pd.Timedelta(days=1),
                "updated_at_kst": now,
                "quality": "연결 대기 일부",
            },
            {
                "dataset": "review_aspect_daily",
                "processed_until_kst": _today_kst(),
                "updated_at_kst": now,
                "quality": "정상",
            },
        ]
    )


# =====================================================================
# Gold B (데이터 관리 화면)  ※ 시각은 UTC 로 저장 -> 표시할 때 to_kst()
# =====================================================================
_TOPICS = ["payments", "orders", "order-items", "members-events"]


@dataset(_TTL_B)
def get_bronze_lag(minutes: int = 180) -> pd.DataFrame:
    """1분 × 토픽 × 파티션 Bronze 적재 지연. 컬럼: collected_at(UTC), topic, partition, end_offset,
    committed_offset, lag_msgs, lag_sec, connector_state.

    S3 Sink 는 15분마다 파일을 쓰므로 정상일 때도 lag_sec 이 0~약 900초를 톱니 모양으로 반복한다.
    이 모양이 '평소'다. 그보다 계속 커지면 이상으로 본다.
    """
    rng = np.random.default_rng(_SEED + 6)
    ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("min"), periods=minutes, freq="min")
    rows = []
    for t in _TOPICS:
        for i, c in enumerate(ts):
            lag_sec = float((i % 15) * 60 + rng.integers(0, 40))
            lag_msgs = int(lag_sec * rng.uniform(0.8, 1.4))
            end = 10_000 + i * 20
            rows.append((c, t, 0, end, end - lag_msgs, lag_msgs, lag_sec, "RUNNING"))
    return pd.DataFrame(
        rows,
        columns=[
            "collected_at",
            "topic",
            "partition",
            "end_offset",
            "committed_offset",
            "lag_msgs",
            "lag_sec",
            "connector_state",
        ],
    )


@dataset(_TTL_B)
def get_payment_attempts(hours: int = 6) -> pd.DataFrame:
    """결제 시도 한 건 = 한 줄 (gold_b.payment_attempts 뷰). 컬럼: payment_id, order_id, attempt_no, pg,
    status, failure_code, failure_cause(PG/CUSTOMER/UNKNOWN), completed_at(UTC), loaded_at(UTC), copies.
    failure_cause 는 뷰가 분류한다. 실패 = PG + CUSTOMER + UNKNOWN 이 항상 성립한다."""
    rng = np.random.default_rng(_SEED + 7)
    n = hours * 90
    end = pd.Timestamp.now(tz="UTC").floor("min")
    completed = end - pd.to_timedelta(rng.integers(0, hours * 60, n), unit="min")
    pg = rng.choice(["PG_A", "PG_B"], n)
    fail = rng.random(n) < 0.08
    # 더미: 최근 30분 PG_A 에서 PG 원인 실패가 늘어난 장면 (시나리오 1 흉내)
    recent_pg_a = (completed > end - pd.Timedelta(minutes=30)) & (pg == "PG_A")
    fail = fail | (recent_pg_a & (rng.random(n) < 0.6))
    codes = np.where(
        recent_pg_a,
        "PG_TIMEOUT",
        rng.choice(["PG_ERROR", "INSUFFICIENT_BALANCE", "CARD_LIMIT_EXCEEDED", "CARD_DECLINED"], n),
    )
    code = np.where(fail, codes, None)
    code_s = pd.Series(code, dtype="object")
    # 실패 원인 분류 (뷰가 하는 일): PG / CUSTOMER / 그 외 UNKNOWN. 성공이면 None.
    cause = pd.Series(None, index=code_s.index, dtype="object")
    cause[fail] = "UNKNOWN"
    cause[code_s.isin(["PG_TIMEOUT", "PG_ERROR"]).to_numpy()] = "PG"
    cause[
        code_s.isin(["INSUFFICIENT_BALANCE", "CARD_LIMIT_EXCEEDED", "CARD_DECLINED"]).to_numpy()
    ] = "CUSTOMER"
    cause = cause.to_numpy()
    return pd.DataFrame(
        {
            "payment_id": [f"p-{i:05d}" for i in range(n)],
            "order_id": [f"o-{i // 1:05d}" for i in range(n)],
            "attempt_no": 1,
            "pg": pg,
            "status": np.where(fail, "FAILED", "SUCCESS"),
            "failure_code": code,
            "failure_cause": cause,
            "completed_at": completed,
            "loaded_at": completed + pd.Timedelta(seconds=40),
            "copies": 1,
        }
    ).sort_values("completed_at")


@dataset(_TTL_B)
def get_malformed_events() -> pd.DataFrame:
    """깨진 필드 한 건 = 한 줄 (malformed_events). 한 메시지에 오류가 여러 개면 여러 줄이다.
    컬럼: topic, kafka_partition, kafka_offset, kafka_timestamp(UTC), field, reason, rule_version.
    reason 은 PARSE_ERROR / MISSING_FIELD / TYPE_MISMATCH / INVALID_VALUE 네 가지.
    메시지 수는 COUNT(*) 가 아니라 위치(topic, partition, offset) 기준으로 센다 (malformed_messages 뷰)."""
    rng = np.random.default_rng(_SEED + 8)
    end = pd.Timestamp.now(tz="UTC").floor("min")
    rows = []
    for i in range(40):
        topic = rng.choice(["clickstream", "payments", "orders"], p=[0.7, 0.15, 0.15])
        ts = end - pd.Timedelta(minutes=int(rng.integers(0, 120)))
        for f, r in [("session_id", "MISSING_FIELD")] + (
            [("event_time", "TYPE_MISMATCH")] if i % 4 == 0 else []
        ):
            rows.append((topic, 0, 18_000 + i, ts, f, r, "0.1.0-draft"))
    return pd.DataFrame(
        rows,
        columns=[
            "topic",
            "kafka_partition",
            "kafka_offset",
            "kafka_timestamp",
            "field",
            "reason",
            "rule_version",
        ],
    )


def to_malformed_messages(events: pd.DataFrame) -> pd.DataFrame:
    """malformed_events -> malformed_messages 뷰와 같은 모양(메시지 1건 = 1줄). 현재 rule_version 만 센다."""
    g = events.groupby(
        ["topic", "kafka_partition", "kafka_offset", "rule_version"], as_index=False
    ).agg(
        kafka_timestamp=("kafka_timestamp", "min"),
        error_count=("field", "nunique"),
        errors=("field", lambda s: ", ".join(sorted(set(s)))),
    )
    return g


@dataset(_TTL_B)
def get_anomalies() -> pd.DataFrame:
    """gold_b.anomaly (탐지 담당 정의). 컬럼은 임시: detected_at(UTC), scenario, target, severity, reason.
    시나리오: PG 장애 / 트래픽 폭주 / 스키마 오염. 실제 컬럼이 정해지면 이 함수만 맞춘다."""
    end = pd.Timestamp.now(tz="UTC").floor("min")
    return pd.DataFrame(
        [
            {
                "detected_at": end - pd.Timedelta(minutes=12),
                "scenario": "PG 장애",
                "target": "PG_A",
                "severity": "높음",
                "reason": "PG 원인 실패 비율 급증 (PG_TIMEOUT)",
            },
            {
                "detected_at": end - pd.Timedelta(minutes=95),
                "scenario": "스키마 오염",
                "target": "clickstream",
                "severity": "중간",
                "reason": "session_id 누락 증가",
            },
        ]
    )


@dataset(_TTL_B)
def get_reprocess_events() -> pd.DataFrame:
    """재처리 단계 한 건 = 한 줄 (reprocess_events). 현재 상태 = 요청별 마지막 줄의 step.
    step: REQUESTED, APPROVED/REJECTED, STARTED, LEDGER_REPLACED, FAILED, REDETECTED, VERIFIED"""
    end = pd.Timestamp.now(tz="UTC").floor("60min")
    rows = [
        (
            "r-001",
            s,
            end - pd.Timedelta(hours=5) + pd.Timedelta(minutes=m),
            a,
            end - pd.Timedelta(hours=7),
            end - pd.Timedelta(hours=6),
            "0.1.1",
            "KAFKA",
        )
        for s, m, a in [
            ("REQUESTED", 0, "판정"),
            ("APPROVED", 10, "담당자"),
            ("STARTED", 20, "재처리 잡"),
            ("LEDGER_REPLACED", 40, "재처리 잡"),
            ("REDETECTED", 50, "판정 잡"),
            ("VERIFIED", 55, "판정 잡"),
        ]
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "request_id",
            "step",
            "at",
            "actor",
            "window_start",
            "window_end",
            "rule_version",
            "source",
        ],
    )


@dataset(_TTL_B)
def get_reliability_checks() -> pd.DataFrame:
    """원장 신뢰성 점검 3종 (오프셋 빈틈 / 중복 / 적재 정지). 문제가 나오면 그 시간대 탐지 결과는 믿지 않는다."""
    now = pd.Timestamp.now(tz="UTC").floor("min")
    return pd.DataFrame(
        [
            {
                "check": "오프셋 빈틈",
                "target": "topic_messages",
                "result": "정상",
                "detail": "빈틈 0건",
                "checked_at": now,
            },
            {
                "check": "중복(같은 topic/partition/offset)",
                "target": "topic_messages",
                "result": "정상",
                "detail": "중복 0건",
                "checked_at": now,
            },
            {
                "check": "적재 정지(2분 초과)",
                "target": "loaded_at / collected_at",
                "result": "정상",
                "detail": "마지막 적재 1분 전",
                "checked_at": now,
            },
        ]
    )
