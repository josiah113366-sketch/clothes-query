"""화면에 쓰는 데이터를 가져오는 함수 모음.

Gold A는 설정에 따라 Athena 완료 실행 또는 미리보기 데이터를 읽는다.
Gold B 등 기존 미리보기 함수의 연결 방식은 유지한다.
  - 「Gold A 설계 정리」 -> order_sales_hourly, product_sales_daily, funnel_session_product,
                           funnel_daily, review_product_daily, review_aspect_daily
  - 「Gold B 칼럼 구성」 -> payment_attempts(뷰), malformed_messages(뷰), malformed_events,
                           bronze_lag_snapshots, reprocess_events
  - gold_b.anomaly 는 탐지 담당이 정의하는 표라서 컬럼은 임시(자리표시)다.
Gold A 실연결은 gold_a_io.py를 호출하며 빈 결과·조회 실패를 더미로 대체하지 않는다.
  Gold A -> S3 gold_a (Athena),  Gold B -> S3 clothes-query-datalake/gold_b/ (Athena DB `gold_b`)

시간 규칙 (노션 문서 기준)
  - Gold A 날짜/시각은 KST 컬럼(*_kst).
  - Gold B 는 UTC 로 저장한다. 화면에 보여줄 때 to_kst() 로 바꾼다.

※ 더미 값은 임의의 숫자이며 실제 결제/리뷰 데이터가 아니다.
※ 리뷰 원문은 내부용이다. 외부 서비스에 올리거나 Git 에 넣지 않는다.
"""

import functools
import json
import logging
import os
import zlib

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


def gold_a_real() -> bool:
    """Gold A는 실연결 모드에서 빈 결과나 실패를 더미로 바꾸지 않는다."""
    mode = os.getenv(
        "GOLD_A_DATA_SOURCE", "athena" if os.getenv("GOLD_A_ATHENA_WORKGROUP") else "dummy"
    )
    if mode not in {"athena", "dummy"}:
        raise ValueError("GOLD_A_DATA_SOURCE는 athena 또는 dummy여야 합니다.")
    return DATA_SOURCE != "dummy" and mode == "athena"


def gold_reader():
    from gold_a_io import GoldAReader

    if "_gold_a_reader" not in st.session_state:
        import boto3

        st.session_state["_gold_a_reader"] = GoldAReader(
            boto3.client("athena", region_name=os.getenv("AWS_REGION", "ap-northeast-1")),
            os.getenv("GOLD_A_ATHENA_WORKGROUP", ""),
            database=os.getenv("GOLD_A_DATABASE", "gold_a"),
        )
    return st.session_state["_gold_a_reader"]


def gold_call(method, *args, **kwargs):
    from gold_a_io import GoldAError

    try:
        return getattr(gold_reader(), method)(*args, **kwargs)
    except (GoldAError, ValueError, TypeError, KeyError) as error:
        st.error(
            str(error)
            if isinstance(error, GoldAError)
            else "Gold A 조회 결과가 배포 명세와 다릅니다."
        )
        st.stop()
    except Exception:  # noqa: BLE001 -- SDK 초기화 실패도 더미로 대체하지 않는다.
        st.error("Gold A 연결에 실패했습니다. AWS 역할·리전·작업그룹 설정을 확인해 주세요.")
        st.stop()


def product_options():
    if gold_a_real():
        return gold_call("products", st.session_state.get("_gold_a_channels", ("trade",)))
    return PRODUCTS


def dataset(ttl: int):
    """Gold A 실연결은 실행별 조회, 기존 경로는 캐시·미리보기 동작을 유지한다.
    데코레이터가 붙은 함수 본문은 더미 생성이다."""

    def deco(dummy_fn):
        name = dummy_fn.__name__

        @st.cache_data(ttl=ttl)
        @functools.wraps(dummy_fn)
        def cached(*args, **kwargs):
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

        @functools.wraps(dummy_fn)
        def wrapper(*args, **kwargs):
            from gold_a_io import TABLES

            table = name.removeprefix("get_")
            if table in TABLES and gold_a_real():
                USING_DUMMY.discard(name)
                if table == "funnel_session_product":
                    import inspect

                    bound = inspect.signature(dummy_fn).bind(*args, **kwargs)
                    bound.apply_defaults()
                    return gold_call("read", table, **bound.arguments)
                return gold_call("read", table, *args, **kwargs)
            return cached(*args, **kwargs)

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
    status, failure_code, failure_cause(PG/CUSTOMER/UNKNOWN), completed_at(UTC), loaded_at(UTC).
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


@dataset(_TTL_B)
def get_rca_reports() -> pd.DataFrame:
    """조사 에이전트의 원인 리포트(더미). 이상(anomaly) 한 건 = 리포트 한 건.

    ※ 노션에는 리포트에 무엇을 넣을지 정해진 내용이 없다 (추후 작업). 아래 컬럼은 제안이며
      조사 에이전트 담당과 맞춘 뒤 바뀔 수 있다.
    컬럼: anomaly_id, rule(R1~R4), scenario, target, detected_at(UTC), summary(원인 요약),
          facts(확인된 사실 목록), assumptions(추정 목록), impact(영향 범위), evidence(근거 목록: 표, 확인 내용),
          action_step(조치 진행: 승인 대기/승인/재처리/재판정/검증), action_at(UTC)
    확인된 사실과 추정을 분리해 보여주는 것이 핵심이다 (노션: 지표 동시 변화는 조사 단서일 뿐 원인 단정 금지).
    """
    end = pd.Timestamp.now(tz="UTC").floor("min")
    return pd.DataFrame(
        [
            {
                "anomaly_id": "a-3f9c01",
                "rule": "R1",
                "scenario": "PG 장애",
                "target": "PG_A",
                "detected_at": end - pd.Timedelta(minutes=12),
                "summary": "PG_A에서 PG 원인 실패(PG_TIMEOUT)가 최근 15분간 급증했습니다.",
                "facts": [
                    "최근 15분 PG_A 결제 중 PG 원인 실패 비율 61% (평소 약 1%)",
                    "PG_B의 PG 원인 실패 비율은 평소 수준",
                    "같은 시간 고객 원인 실패 비율에는 변화 없음",
                ],
                "assumptions": [
                    "PG_A 쪽 장애일 가능성이 높으나 PG 사의 공지는 확인하지 못함",
                    "실패한 주문이 다른 PG로 재시도되어 최종 성공했는지는 미확인",
                ],
                "impact": "실패 결제 시도 약 40건, 영향 주문 약 35건. 같은 시간 승인 금액 감소 여부는 Gold A 주문·매출에서 확인 필요",
                "evidence": [
                    {
                        "table": "gold_b.payment_attempts",
                        "finding": "PG_A 실패 코드 분포: PG_TIMEOUT 대부분",
                    },
                    {
                        "table": "gold_b.bronze_lag_snapshots",
                        "finding": "같은 시간 적재 지연은 평소 범위 (데이터 지연 아님)",
                    },
                    {
                        "table": "gold_b.malformed_messages",
                        "finding": "같은 시간 깨진 메시지 증가 없음",
                    },
                ],
                "action_step": "승인 대기",
                "action_at": end - pd.Timedelta(minutes=10),
            },
            {
                "anomaly_id": "a-81be77",
                "rule": "R4",
                "scenario": "스키마 오염",
                "target": "clickstream",
                "detected_at": end - pd.Timedelta(minutes=95),
                "summary": "clickstream 메시지에서 session_id 누락이 증가했습니다.",
                "facts": [
                    "최근 2시간 clickstream 깨진 메시지 중 MISSING_FIELD(session_id)가 대부분",
                    "오염 시작 시점은 가장 이른 kafka_timestamp 기준 약 2시간 전",
                ],
                "assumptions": ["보내는 쪽(시뮬레이터) 변경이 원인일 수 있으나 변경 이력은 미확인"],
                "impact": "구매 퍼널 집계(첫 조회→주문 연결)에 영향 가능. 재처리 범위는 오염 시작~원인 수정 시각",
                "evidence": [
                    {
                        "table": "gold_b.malformed_events",
                        "finding": "field=session_id, reason=MISSING_FIELD 집중",
                    },
                    {
                        "table": "gold_b.topic_messages",
                        "finding": "유입량은 평소와 같음 (폭주 아님)",
                    },
                ],
                "action_step": "재처리",
                "action_at": end - pd.Timedelta(minutes=30),
            },
        ]
    )


# =====================================================================
# 감성분석 모델 관리 (데이터 관리 > '감성분석 모델' 화면)
#   실데이터 연결 시 읽을 곳 (athena-review-score 스택, Glue DB):
#     review_aspect_scores   점수 테이블 (review_id, aspect, score, model_version, model_version_no, analyzed_at, review_date)
#     review_score_log       후기별 점수 로그 (속성이 0개인 후기도 n_aspects = 0 으로 한 줄)
#     review_aspect_scores_latest 뷰   Gold 가 읽는 값 (후기마다 model_version_no 가 가장 큰 결과)
#   점수는 -2 ~ +2, '미언급'은 행이 없다. 시각 컬럼(analyzed_at)은 UTC 로 가정하고 화면에서 KST 로 바꾼다.
#   ※ 아래 모델 이름·숫자는 모두 더미다. 후기 원문은 점수 데이터에 없고(review_id 만) get_review_texts 로 따로 읽는다.
# =====================================================================
# (모델 이름, model_version_no). 번호 규칙: 평가 모델/로직이 바뀌면 메이저, 작은 수정이면 마이너를 올린다.
_MODELS = [("2.3_score_s2c", 0.0), ("2.4b_score_s2c", 1.0)]
SCORES = [-2, -1, 0, 1, 2]  # 속성별 점수 값


@dataset(_TTL_A)
def get_model_registry() -> pd.DataFrame:
    """모델 버전 1줄. 컬럼: model_version, model_version_no, gold_read(Gold 가 읽는 버전인지), deployed_at(UTC),
    change_type(최초/메이저/마이너), summary(한 줄 요약), rescore_required(기존 후기 재점수화 대상인지),
    based_on(되돌림 버전이면 원래 버전 이름), notes(배포 뒤 정정·추가 [{date, text}]),
    last_analyzed_at(UTC), analyzed_reviews, unscored_reviews(현재 버전만. 옛 버전은 NaN. S3 패치노트만 읽을 때는 모두 비어 있다),
    eval_set, eval_n, f1, mae, qwk(오프라인 평가 지표, 패치노트의 evaluation).
    실데이터: MODEL_REGISTRY_URI 가 있으면 S3 패치노트(_real_model_registry)를 읽는다."""
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).floor("60min")
    return pd.DataFrame(
        {
            "model_version": [m for m, _ in _MODELS],
            "model_version_no": [n for _, n in _MODELS],
            "gold_read": [False, True],
            "change_type": ["최초", "메이저"],
            "summary": [
                "점수 모델 첫 배포",
                "LoRA 병합 배포, 극단 점수 학습 보강, 출력 형식 정리, 평가 세트 교체",
            ],
            "rescore_required": [False, True],
            "deployed_at": [now - pd.Timedelta(days=40), now - pd.Timedelta(days=12)],
            "based_on": [None, None],
            "notes": [[], [{"date": "2026-10-20", "text": "예시: 평가 세트 이름 표기 정정"}]],
            "last_analyzed_at": [now - pd.Timedelta(days=12), now - pd.Timedelta(hours=7)],
            "analyzed_reviews": [7_940, 3_410],
            "unscored_reviews": [np.nan, 281.0],
            "eval_set": ["사람 평가 세트 v1", "사람 평가 세트 v2"],
            "eval_n": [99, 99],
            "f1": [0.842, 0.868],
            "mae": [0.301, 0.263],
            "qwk": [0.891, 0.915],
        }
    )


@dataset(_TTL_A)
def get_model_changelog() -> pd.DataFrame:
    """버전별 패치노트 항목. 컬럼: model_version, category, item, detail.
    category: 모델 / 학습 데이터 / 프롬프트·후처리 / 속성 목록 / 평가 / 배포.
    실데이터: review-analysis/releases/<버전>.yaml 의 changes (S3 로 배포된 JSON, _real_model_changelog).
    ※ 아래 내용은 화면 구성을 보기 위한 예시다."""
    rows = [
        ("2.3_score_s2c", "모델", "초판", "속성별 점수(-2~+2)를 직접 내는 점수 모델 첫 배포"),
        (
            "2.3_score_s2c",
            "속성 목록",
            "속성 11개",
            "사이즈·핏 ~ 활용성·사용감 11개 속성을 대상으로 함",
        ),
        ("2.3_score_s2c", "평가", "사람 평가 세트 v1", "99건 기준 F1 0.842, MAE 0.301, QWK 0.891"),
        (
            "2.4b_score_s2c",
            "모델",
            "LoRA 병합 배포",
            "어댑터를 기본 모델에 병합해 배포 형태를 바꿈",
        ),
        (
            "2.4b_score_s2c",
            "학습 데이터",
            "극단 점수 보강",
            "-2, +2 예시를 더 넣어 약한 부정·강한 긍정 구분을 개선",
        ),
        (
            "2.4b_score_s2c",
            "프롬프트·후처리",
            "출력 형식",
            "속성별 한 줄 출력. 파싱 실패 후기는 다음 실행에서 다시 시도",
        ),
        (
            "2.4b_score_s2c",
            "평가",
            "평가 세트 교체",
            "사람 평가 세트 v2로 바뀜. 이전 버전 수치와 직접 비교할 수 없음",
        ),
        (
            "2.4b_score_s2c",
            "배포",
            "전체 재점수화",
            "메이저 번호가 올라 기존 후기가 모두 재점수화 대상이 됨",
        ),
    ]
    return pd.DataFrame(rows, columns=["model_version", "category", "item", "detail"])


# ---- 실데이터: 모델 버전·패치노트 (S3 model-registry) ----------------------
# 패치노트는 review-analysis/releases/<버전>.yaml 로 git 에 쓰고, 모델을 올릴 때(upload_model.py) JSON 으로 바뀌어 S3 에 올라간다.
#   <MODEL_REGISTRY_URI>index.json        버전 목록 {schema, versions:[{model_version, model_version_no, change_type, released_at, summary, based_on}]}
#   <MODEL_REGISTRY_URI><버전>.json        버전 하나의 패치노트 (changes, evaluation, rescore_required, notes, based_on ...)
# 릴리스 묶음(manifest)이 있는 버전만 올라가므로 여기 보이는 버전 = 실제로 배포할 수 있는 버전이다.
# MODEL_REGISTRY_URI: s3://<버킷>/review-score/model-registry/releases/ (끝에 / 필수). 버킷 이름은 코드에 두지 않고 환경변수로만 받는다.
#   비어 있으면 등록하지 않아 더미를 쓴다. 읽기 권한(Pod Identity)은 infra 쪽 작업이다(TODO F4).
# 양식 번호(schema)가 아래 값과 다르면 읽지 않고 더미로 대체한다(release_notes.py 의 SCHEMA 와 맞춘다).
MODEL_REGISTRY_URI = os.getenv("MODEL_REGISTRY_URI", "")
_RELEASE_SCHEMA = 1


@st.cache_data(ttl=_TTL_A)
def _read_releases(uri: str) -> list:
    """S3 에서 index.json 과 버전별 패치노트 JSON 을 읽어 문서 목록을 돌려준다. 실패하면 예외(=> 더미 대체)."""
    import boto3  # 실데이터를 쓸 때만 필요하다

    if not (uri.startswith("s3://") and uri.endswith("/")):
        raise ValueError("MODEL_REGISTRY_URI 는 s3://<버킷>/<경로>/ 형식이어야 합니다")
    bucket, prefix = uri[5:].split("/", 1)
    s3 = boto3.client("s3")

    def get(key):
        doc = json.loads(s3.get_object(Bucket=bucket, Key=prefix + key)["Body"].read())
        if doc.get("schema") != _RELEASE_SCHEMA:
            raise ValueError(f"{key}: schema {doc.get('schema')} 를 읽을 수 없습니다")
        return doc

    index = get("index.json")
    return [get(f"{v['model_version']}.json") for v in index.get("versions", [])]


def _kst_date_to_utc(d: str) -> pd.Timestamp:
    """패치노트의 날짜(KST, YYYY-MM-DD)를 화면 규칙(UTC 저장 -> to_kst 로 표시)에 맞게 UTC 로 바꾼다."""
    return pd.Timestamp(d) - pd.Timedelta(hours=9)


def _real_model_registry() -> pd.DataFrame:
    docs = _read_releases(MODEL_REGISTRY_URI)
    if not docs:
        return pd.DataFrame()
    top = max(float(d["model_version_no"]) for d in docs)
    rows = []
    for d in docs:
        ev = d.get("evaluation") or {}
        rows.append(
            {
                "model_version": d["model_version"],
                "model_version_no": float(d["model_version_no"]),
                # Gold 는 후기마다 번호가 가장 큰 결과를 읽는다. 배포된 가장 큰 번호를 'Gold 가 읽는 버전'으로 본다.
                "gold_read": float(d["model_version_no"]) == top,
                "change_type": d["change_type"],
                "summary": d["summary"],
                "rescore_required": bool(d["rescore_required"]),
                "deployed_at": _kst_date_to_utc(d["released_at"]),
                "based_on": d.get("based_on"),
                "notes": d.get("notes") or [],
                # 분석 현황은 점수 테이블(Athena) 연결 후 채운다(TODO B6). 그 전에는 비워 둔다.
                "last_analyzed_at": pd.NaT,
                "analyzed_reviews": np.nan,
                "unscored_reviews": np.nan,
                "eval_set": ev.get("eval_set"),
                "eval_n": ev.get("eval_n"),
                "f1": ev.get("f1"),
                "mae": ev.get("mae"),
                "qwk": ev.get("qwk"),
            }
        )
    return pd.DataFrame(rows)


def _real_model_changelog() -> pd.DataFrame:
    rows = [
        (d["model_version"], c["category"], c["item"], c["detail"])
        for d in _read_releases(MODEL_REGISTRY_URI)
        for c in d.get("changes") or []
    ]
    return pd.DataFrame(rows, columns=["model_version", "category", "item", "detail"])


if MODEL_REGISTRY_URI:
    _REAL["get_model_registry"] = _real_model_registry
    _REAL["get_model_changelog"] = _real_model_changelog


@dataset(_TTL_A)
def get_model_review_daily(days: int = 30) -> pd.DataFrame:
    """작성일(KST) × 모델 버전별 분석한 후기 수. 컬럼: review_date, model_version, analyzed_review_count,
    zero_aspect_review_count(속성이 0개 나온 후기 수)."""
    rng = np.random.default_rng(_SEED + 20)
    dates = pd.date_range(end=_today_kst(), periods=days)
    rows = []
    for m, _ in _MODELS:
        for d in dates:
            n = int(rng.integers(240, 320))
            rows.append((d, m, n, int(n * rng.uniform(0.04, 0.09))))
    return pd.DataFrame(
        rows,
        columns=[
            "review_date",
            "model_version",
            "analyzed_review_count",
            "zero_aspect_review_count",
        ],
    )


@dataset(_TTL_A)
def get_model_score_daily(days: int = 30) -> pd.DataFrame:
    """작성일(KST) × 모델 버전 × 속성 × 점수별 후기 수. 컬럼: review_date, model_version, aspect, score,
    review_count. 한 후기는 속성마다 점수가 하나이므로 review_count 의 속성별 합 = 그 속성을 언급한 후기 수.
    속성끼리 더하면 후기 하나가 여러 번 세어지므로 전체 후기 수로 쓰지 않는다."""
    rng = np.random.default_rng(_SEED + 21)
    dates = pd.date_range(end=_today_kst(), periods=days)
    rows = []
    for vi, (m, _) in enumerate(_MODELS):
        for ai, aspect in enumerate(ASPECTS):
            # 속성마다 점수 분포가 다르다 (뒤쪽 속성일수록 부정이 조금 많게). 새 버전은 극단 점수를 더 낸다.
            base = np.array([0.04 + 0.01 * ai, 0.10, 0.20, 0.36 - 0.01 * ai, 0.30 - 0.03 * vi])
            base = base + np.array([0.02 * vi, 0, 0, 0, 0.02 * vi])
            base = base / base.sum()
            for d in dates:
                mentioned = int(rng.integers(20, 90))
                counts = rng.multinomial(mentioned, base)
                rows.extend((d, m, aspect, s, int(c)) for s, c in zip(SCORES, counts))
    return pd.DataFrame(
        rows, columns=["review_date", "model_version", "aspect", "score", "review_count"]
    )


@dataset(_TTL_A)
def get_model_score_diff(model_a: str, model_b: str) -> pd.DataFrame:
    """같은 후기·속성에 대한 두 버전의 점수 비교. 컬럼: review_id, aspect, score_a, score_b.
    두 버전이 모두 점수를 낸 (후기, 속성) 쌍만 있다. 후기 원문은 get_review_texts 로 따로 읽는다."""
    rng = np.random.default_rng(_SEED + 22 + zlib.crc32(f"{model_a}|{model_b}".encode()) % 1000)
    n = 900
    a = rng.choice(SCORES, n, p=[0.06, 0.14, 0.2, 0.36, 0.24])
    change = rng.random(n) < 0.18
    step = rng.choice([-2, -1, 1, 2], n, p=[0.1, 0.4, 0.4, 0.1])
    b = np.clip(np.where(change, a + step, a), -2, 2)
    return pd.DataFrame(
        {
            "review_id": [f"R-{i // 3 + 1:05d}" for i in range(n)],
            "aspect": rng.choice(ASPECTS, n),
            "score_a": a,
            "score_b": b,
        }
    )


# 더미 후기 문장 재료. 속성마다 (좋은 말, 나쁜 말). 실제 후기에서 가져온 문장이 아니다(직접 지은 예시).
_DUMMY_PHRASES = {
    "사이즈·핏": ("정사이즈로 잘 맞아요", "생각보다 한 치수 작게 나왔어요"),
    "품질·내구성": ("박음질이 꼼꼼해요", "두 번 입었는데 보풀이 일어나요"),
    "재질·촉감": ("촉감이 부드러워요", "까슬까슬해서 안에 받쳐 입어야 해요"),
    "색상": ("화면이랑 색이 똑같아요", "사진보다 색이 많이 어두워요"),
    "디자인": ("디자인이 깔끔해서 자주 입어요", "실물은 핏이 좀 밋밋해요"),
    "가격": ("이 가격이면 만족해요", "가격에 비해 아쉬워요"),
    "배송": ("배송이 빨랐어요", "배송이 일주일 넘게 걸렸어요"),
    "포장": ("포장이 깔끔했어요", "포장이 뜯겨서 왔어요"),
    "세탁·관리": ("세탁해도 줄지 않아요", "한 번 빨았는데 늘어났어요"),
    "활용성·사용감": ("여기저기 잘 어울려요", "막상 입을 일이 별로 없네요"),
}
_DUMMY_TAILS = [
    "",
    " 재구매 의사 있어요.",
    " 그래도 쓸 만해요.",
    " 다른 색도 살까 고민 중이에요.",
    " 교환할까 해요.",
]


@dataset(_TTL_A)
def get_review_texts(review_ids: tuple[str, ...]) -> pd.DataFrame:
    """후기 원문. 컬럼: review_id, review_text, rating(별점 1~5).

    감성분석 모델 화면에서 '점수 차가 큰 후기'를 사람이 직접 읽고 어느 버전이 맞는지 판단하는 데 쓴다.
    실데이터: Silver 리뷰 표에서 review_id 로 조회해 _REAL["get_review_texts"] 에 등록한다 (TODO.md B8).
    review_ids 는 캐시 키가 되도록 tuple 로 받는다.
    ※ 원문은 팀 내부용이다 (대시보드는 허용 IP·로그인 뒤에서만 열린다). 외부 서비스로 보내거나 Git 에 넣지 않는다.
    ※ 더미 문장은 직접 지은 예시 문장이며 실제 후기가 아니다. 앞에 [더미] 를 붙인다.
    """
    keys = [a for a in ASPECTS if a in _DUMMY_PHRASES]
    rows = []
    for rid in review_ids:
        rng = np.random.default_rng(_SEED + zlib.crc32(rid.encode()))
        picked = rng.choice(keys, size=int(rng.integers(1, 4)), replace=False)
        parts = [_DUMMY_PHRASES[a][int(rng.random() < 0.45)] for a in picked]
        text = (
            "[더미] "
            + ", ".join(parts)
            + "."
            + _DUMMY_TAILS[int(rng.integers(0, len(_DUMMY_TAILS)))]
        )
        rows.append((rid, text, int(rng.integers(1, 6))))
    return pd.DataFrame(rows, columns=["review_id", "review_text", "rating"])


@dataset(_TTL_B)
def get_model_runs(days: int = 14) -> pd.DataFrame:
    """일별 분석 Job 실행 기록. 컬럼: run_date(작성일 KST), model_version, status(SUCCEEDED/FAILED/
    SKIPPED_NO_INPUT), input_reviews(미점수로 고른 후기), scored_reviews(점수가 한 개 이상 나온 후기),
    zero_aspect_reviews, parse_failed(파싱 실패. 다음 실행에서 다시 시도), unscored_left(실행 뒤 남은 미점수),
    duration_min, finished_at(UTC). 실제로는 Airflow 실행 기록과 오류 prefix 에서 가져온다."""
    rng = np.random.default_rng(_SEED + 23)
    dates = pd.date_range(end=_today_kst(), periods=days)
    cur = _MODELS[-1][0]
    rows = []
    for i, d in enumerate(dates):
        inp = int(rng.integers(240, 320))
        status, failed, scored = "SUCCEEDED", int(rng.integers(0, 3)), 0
        if i == days - 6:
            status, inp = "SKIPPED_NO_INPUT", 0  # 미점수 후기가 없으면 Job 을 띄우지 않는다
        elif i == days - 3:
            status = "FAILED"
        zero = int(inp * rng.uniform(0.04, 0.09))
        if status == "SUCCEEDED":
            scored = inp - zero - failed
        rows.append(
            (
                d,
                cur,
                status,
                inp,
                scored,
                zero if status == "SUCCEEDED" else 0,
                failed if status == "SUCCEEDED" else 0,
                inp if status == "FAILED" else failed if status == "SUCCEEDED" else 0,
                float(rng.uniform(9, 16)) if status != "SKIPPED_NO_INPUT" else 0.0,
                d + pd.Timedelta(hours=16, minutes=int(rng.integers(0, 40))),
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "run_date",
            "model_version",
            "status",
            "input_reviews",
            "scored_reviews",
            "zero_aspect_reviews",
            "parse_failed",
            "unscored_left",
            "duration_min",
            "finished_at",
        ],
    )


# =====================================================================
# 데이터 흐름도 (파이프라인 상태 > 데이터 흐름)  ※ 더미 없음
# =====================================================================
# 이 화면은 더미로 그리지 않는다 (lemin 2026-10-24). 다른 get_* 와 달리 @dataset 을 쓰지 않으므로
# 실데이터를 못 읽으면 더미로 바꾸지 않고, 그 단계를 회색(미연결 / 확인 불가)으로 둔다.
#
# Athena 접속: DASHBOARD_ATHENA_WORKGROUP (없으면 승인 화면의 APPROVAL_ATHENA_WORKGROUP), AWS_REGION.
#   workgroup 이 없으면 Athena 로 읽는 단계 전부가 '미연결'이다.
#   읽기 권한(Athena + S3 gold_b/ · silver/runtime/ · gold_a/catalog/ + Glue)은 대시보드 Pod Identity 가 필요하다 (TODO F3).
ATHENA_WORKGROUP = os.getenv("DASHBOARD_ATHENA_WORKGROUP") or os.getenv(
    "APPROVAL_ATHENA_WORKGROUP", ""
)
if ATHENA_WORKGROUP.startswith(
    "<"
):  # deployment.yaml 의 자리표시("<대시보드용 workgroup>")는 미설정으로 본다
    ATHENA_WORKGROUP = ""
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")

# 판정 기준(초). 운영하며 조정한다.
FLOW_SINK_LAG_WARN = (
    900 + 120
)  # S3 Sink 는 15분마다 파일을 쓴다. 파이프라인 탭 NORMAL_MAX_SEC 과 같은 값
FLOW_COLLECTOR_WARN, FLOW_COLLECTOR_BAD = 120, 300  # 수집기는 1분마다 잰다
FLOW_NO_INFLOW_MIN = 10  # Kafka 유입이 이만큼(분) 없으면 지연
FLOW_GOLD_B_WARN = 10 * 60  # Gold B 적재 잡은 1분마다 쌓는다
FLOW_BATCH_WARN = 26 * 3600  # 하루 1회 배치(Silver·Gold A): 마지막 완료가 26시간보다 오래되면 지연
FLOW_REVIEW_WARN = 26 * 3600  # 리뷰 시뮬레이터는 하루 1번(UTC 00:30) S3 에 바로 쓴다
# CDC 커넥터(connectors/cdc-source.yaml)가 RDS 표를 옮겨 쓰는 토픽. clickstream 은 CDC 가 아니라서 뺀다
_CDC_TOPICS = ("members-events", "orders", "order-items", "payments")
# 데이터 레이크 버킷 (리뷰 Bronze 목록 조회용). 저장소에 적어도 되는 이름이라 기본값으로 둔다
DATALAKE_BUCKET = os.getenv("DATALAKE_BUCKET", "clothes-query-datalake")


def _athena(sql: str) -> pd.DataFrame:
    """Athena 에 SELECT 를 한 번 보내고 결과를 문자열 DataFrame 으로 돌려준다. 실패하면 예외.
    값 형변환은 부르는 쪽에서 한다 (컬럼이 몇 개 안 돼서 그쪽이 더 읽기 쉽다)."""
    import time

    import boto3  # 실데이터를 쓸 때만 필요하다

    if not ATHENA_WORKGROUP:
        raise RuntimeError("Athena workgroup 환경변수가 없습니다")
    client = boto3.client("athena", region_name=AWS_REGION)
    qid = client.start_query_execution(QueryString=sql, WorkGroup=ATHENA_WORKGROUP)[
        "QueryExecutionId"
    ]
    deadline = time.monotonic() + 30  # 화면이 오래 멈추지 않게 30초에서 끊는다
    while True:
        st_ = client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st_["State"] == "SUCCEEDED":
            break
        if st_["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(st_.get("StateChangeReason", st_["State"]))
        if time.monotonic() > deadline:
            client.stop_query_execution(QueryExecutionId=qid)
            raise TimeoutError("Athena 조회 30초 초과")
        time.sleep(0.5)
    rows, cols = [], None
    for page in client.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        rs = page["ResultSet"]
        if cols is None:
            cols = [c["Name"] for c in rs["ResultSetMetadata"]["ColumnInfo"]]
            data_rows = rs["Rows"][1:]  # 첫 줄은 컬럼 이름
        else:
            data_rows = rs["Rows"]
        rows += [[d.get("VarCharValue") for d in r["Data"]] for r in data_rows]
    return pd.DataFrame(rows, columns=cols)


def _utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def _hour_partitions(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """UTC dt/hour 파티션 조건. projection 표라서 이 조건이 있어야 스캔량이 KB 단위로 끝난다."""
    hours = pd.date_range(start.floor("h"), end.floor("h"), freq="h")
    return " OR ".join(f"(dt = '{h:%Y-%m-%d}' AND hour = '{h:%H}')" for h in hours)


def _real_bronze_lag(minutes: int = 180) -> pd.DataFrame:
    """gold_b.bronze_lag_snapshots 최근 minutes 분. 컬럼 이름 kafka_partition 은 화면 규칙(partition)으로 바꾼다."""
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(minutes=minutes)
    df = _athena(
        "SELECT collected_at, topic, kafka_partition, end_offset, committed_offset, lag_msgs, lag_sec,"
        " connector_state FROM gold_b.bronze_lag_snapshots"
        f" WHERE ({_hour_partitions(start, now)})"
        f" AND collected_at >= TIMESTAMP '{start:%Y-%m-%d %H:%M:%S}'"  # collected_at 은 UTC
    ).rename(columns={"kafka_partition": "partition"})
    df["collected_at"] = _utc(df.collected_at)
    for c in ["partition", "end_offset", "committed_offset", "lag_msgs", "lag_sec"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


MALFORMED_HOURS = 6  # 형식 오류 화면이 읽는 최근 시간 (TODO B1)
REPROCESS_DAYS = 7  # 재처리 이력 화면이 읽는 최근 날짜 (TODO B1)


def _real_payment_attempts(hours: int = 6, *, query=None, now=None) -> pd.DataFrame:
    """gold_b.payment_attempts 뷰의 최근 hours 시간(completed_at). 보류 안 된 결제 하나 = 한 줄.
    뷰가 원장 전체를 읽어서 시간 폴더 조건은 쓸 수 없다. 대시보드 역할에 뷰(payment_states·payment_attempts) 읽기 권한이 필요하다."""
    start = (now or pd.Timestamp.now(tz="UTC")) - pd.Timedelta(hours=hours)
    df = (query or _athena)(
        "SELECT payment_id, order_id, attempt_no, pg, status, failure_code, failure_cause,"
        " completed_at, loaded_at FROM gold_b.payment_attempts"
        f" WHERE completed_at >= TIMESTAMP '{start:%Y-%m-%d %H:%M:%S}'"  # completed_at 은 UTC
        " ORDER BY completed_at"
    )
    df["attempt_no"] = pd.to_numeric(df["attempt_no"], errors="coerce")
    for c in ("completed_at", "loaded_at"):
        df[c] = _utc(df[c])
    return df


def _real_malformed_events(*, query=None, now=None) -> pd.DataFrame:
    """gold_b.malformed_events 의 최근 MALFORMED_HOURS 시간(kafka_timestamp). 오류 하나 = 한 줄."""
    end = now or pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(hours=MALFORMED_HOURS)
    df = (query or _athena)(
        "SELECT topic, kafka_partition, kafka_offset, kafka_timestamp, field, reason, rule_version"
        " FROM gold_b.malformed_events"
        f" WHERE ({_hour_partitions(start, end)})"
        f" AND kafka_timestamp >= TIMESTAMP '{start:%Y-%m-%d %H:%M:%S}'"  # kafka_timestamp 는 UTC
        " ORDER BY kafka_timestamp"
    )
    for c in ("kafka_partition", "kafka_offset"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["kafka_timestamp"] = _utc(df["kafka_timestamp"])
    return df


def _real_reprocess_events(*, query=None, now=None) -> pd.DataFrame:
    """gold_b.reprocess_events 의 최근 REPROCESS_DAYS 일. 시간 폴더가 없는 작은 표다. at 칸은 따옴표로 감싼다."""
    start = (now or pd.Timestamp.now(tz="UTC")) - pd.Timedelta(days=REPROCESS_DAYS)
    df = (query or _athena)(
        'SELECT request_id, step, "at", actor, window_start, window_end, rule_version, source'
        " FROM gold_b.reprocess_events"
        f" WHERE \"at\" >= TIMESTAMP '{start:%Y-%m-%d %H:%M:%S}'"
        ' ORDER BY "at"'
    )
    for c in ("at", "window_start", "window_end"):
        df[c] = _utc(df[c])
    return df


if ATHENA_WORKGROUP:
    # 파이프라인 상태 > 지연·점검 탭도 실데이터를 쓰게 한다 (못 읽으면 그 탭은 기존처럼 더미로 대체)
    _REAL["get_bronze_lag"] = _real_bronze_lag
    # 결제 관제·형식 오류·재처리 이력 (TODO B1). 못 읽거나 결과가 없으면 각 화면은 더미로 대체한다
    _REAL["get_payment_attempts"] = _real_payment_attempts
    _REAL["get_malformed_events"] = _real_malformed_events
    _REAL["get_reprocess_events"] = _real_reprocess_events


def _ago(sec: float) -> str:
    """'n초 전 / n분 전 / n시간 전' 문구."""
    if sec < 120:
        return f"{sec:,.0f}초 전"
    if sec < 2 * 3600:
        return f"{sec / 60:,.0f}분 전"
    return f"{sec / 3600:,.1f}시간 전"


def _kst_hm(ts: pd.Timestamp) -> str:
    """UTC 시각을 화면용 KST 'MM-DD HH:MM' 으로."""
    return ts.tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")


def _flow_from_lag(now: pd.Timestamp) -> dict:
    """지연 수집기 표 하나로 RDS · CDC · Kafka · S3 Sink · Bronze · 수집기 여섯 단계를 판정한다.

    RDS 와 CDC 는 직접 재지 않는다(대시보드는 RDS 에 접속하지 않고, 커넥터 상태도 수집기가 기록하지 않는다).
    대신 CDC 커넥터가 쓰는 토픽(_CDC_TOPICS)의 end_offset 이 늘어나는지로 '추정'한다:
      늘어남      -> RDS 쓰기와 CDC 둘 다 돌고 있다 (정상, 값 앞에 '추정')
      10분간 그대로 -> CDC 는 지연, RDS 는 원인이 RDS 인지 CDC 인지 알 수 없어 '확인 불가'
    """
    lag = _real_bronze_lag(70)  # 최근 1시간 + 여유
    if lag.empty:
        return {
            "collector": (
                "bad",
                "측정 없음",
                "최근 70분 동안 bronze_lag_snapshots 에 쌓인 행이 없습니다",
            )
        }
    out = {}
    last = lag.collected_at.max()
    age = (now - last).total_seconds()
    st_c = "bad" if age > FLOW_COLLECTOR_BAD else "warn" if age > FLOW_COLLECTOR_WARN else "ok"
    out["collector"] = (
        st_c,
        _ago(age) + " 측정",
        f"마지막 측정 {_kst_hm(last)} KST · 1분마다 측정",
    )
    if st_c == "bad":
        # 측정이 멈추면 아래 세 단계는 판단할 근거가 없다. 정상으로 칠하지 않는다
        why = "지연 수집기 측정이 멈춰 판단할 수 없습니다"
        return out | {
            k: ("unknown", "확인 불가", why) for k in ("rds", "cdc", "kafka", "sink", "bronze")
        }

    latest = lag[lag.collected_at == last]
    # Kafka: 토픽별 end_offset 증가량. 최근 10분과 1시간 평균 분당 유입
    per_topic = lag.groupby(["collected_at", "topic"]).end_offset.sum().unstack().sort_index()
    recent = per_topic[per_topic.index >= last - pd.Timedelta(minutes=FLOW_NO_INFLOW_MIN)]
    inflow_10 = (
        float((recent.iloc[-1] - recent.iloc[0]).clip(lower=0).sum()) if len(recent) > 1 else np.nan
    )
    span_min = max((per_topic.index[-1] - per_topic.index[0]).total_seconds() / 60, 1)
    inflow_hr = float((per_topic.iloc[-1] - per_topic.iloc[0]).clip(lower=0).sum()) / span_min
    quiet = [
        t for t in recent.columns if len(recent) > 1 and recent[t].iloc[-1] <= recent[t].iloc[0]
    ]
    detail = f"최근 1시간 평균 분당 {inflow_hr:,.1f}건 · 토픽 {per_topic.shape[1]}개"
    if quiet:
        detail += f"\n{FLOW_NO_INFLOW_MIN}분간 유입 없음: {', '.join(quiet)}"
    if np.isnan(inflow_10):
        out["kafka"] = ("unknown", "확인 불가", "측정이 2회 미만입니다")
    else:
        out["kafka"] = (
            "warn" if inflow_10 == 0 else "ok",
            f"분당 {inflow_10 / FLOW_NO_INFLOW_MIN:,.1f}건",
            detail,
        )
    # RDS · CDC: CDC 토픽들의 최근 10분 유입으로 추정 (위 Kafka 계산과 같은 표를 쓴다)
    cdc_cols = [t for t in recent.columns if t in _CDC_TOPICS]
    if len(recent) > 1 and cdc_cols:
        cdc_in = float((recent[cdc_cols].iloc[-1] - recent[cdc_cols].iloc[0]).clip(lower=0).sum())
        why = f"CDC 토픽({', '.join(cdc_cols)})의 최근 {FLOW_NO_INFLOW_MIN}분 유입으로 추정. 커넥터 상태를 직접 읽지는 않습니다"
        if cdc_in > 0:
            per_min = f"추정 · 분당 {cdc_in / FLOW_NO_INFLOW_MIN:,.1f}건"
            out["cdc"] = ("ok", per_min, why)
            out["rds"] = ("ok", "추정 · 쓰기 있음", why)
        else:
            out["cdc"] = (
                "warn",
                f"{FLOW_NO_INFLOW_MIN}분간 유입 없음",
                why + "\nKafka Connect 의 CDC 커넥터 상태를 확인",
            )
            out["rds"] = (
                "unknown",
                "확인 불가",
                "CDC 토픽 유입이 멈춰 RDS 쓰기가 멈춘 것인지 CDC 가 멈춘 것인지 알 수 없습니다",
            )
    # S3 Sink v2: 커넥터 상태 + 지연 초
    states = sorted(set(latest.connector_state.dropna()))
    max_lag = float(latest.lag_sec.max())
    detail = f"커넥터 {', '.join(states) or '-'} · 밀린 메시지 {int(latest.lag_msgs.sum()):,}건"
    if any(s != "RUNNING" for s in states):
        out["sink"] = ("bad", " / ".join(states), detail)
    else:
        out["sink"] = (
            "warn" if max_lag > FLOW_SINK_LAG_WARN else "ok",
            f"지연 {max_lag:,.0f}초",
            detail,
        )
    # Bronze: committed_offset 이 마지막으로 올라간 시각 = 마지막으로 Bronze 파일이 써진 시각
    committed = lag.groupby("collected_at").committed_offset.sum().sort_index()
    moved = committed.index[committed.diff() > 0]
    if len(moved):
        age_b = (now - moved.max()).total_seconds()
        out["bronze"] = (
            "warn" if age_b > FLOW_SINK_LAG_WARN else "ok",
            _ago(age_b) + " 적재",
            f"committed offset 이 마지막으로 늘어난 측정 {_kst_hm(moved.max())} KST",
        )
    else:
        out["bronze"] = (
            "warn",
            "1시간 적재 없음",
            "최근 70분 동안 committed offset 이 늘지 않았습니다",
        )
    return out


def _flow_from_silver(now: pd.Timestamp) -> dict:
    """silver.silver_runs (거래 Silver 완료 기록) 마지막 한 줄."""
    df = _athena(
        "SELECT run_id, completed_at, status, quality_status, row_count FROM silver.silver_runs"
        " ORDER BY completed_at DESC LIMIT 1"
    )
    if df.empty:
        return {"s_trade": ("warn", "완료 기록 없음", "silver.silver_runs 에 행이 없습니다")}
    r = df.iloc[0]
    at = _utc(pd.Series([r.completed_at])).iloc[0]
    age = (now - at).total_seconds()
    detail = f"run {r.run_id} · 품질 {r.quality_status} · {int(float(r.row_count or 0)):,}행"
    if r.status != "COMPLETED":
        status = "bad"
    elif age > FLOW_BATCH_WARN or r.quality_status != "PASS":
        status = "warn"
    else:
        status = "ok"
    return {"s_trade": (status, f"{_kst_hm(at)} 완료", detail)}


# Gold A channel(실행 단위) -> 흐름도 단계. 표 이름은 pipelines/gold_publication.py METRICS 와 같다
_GOLD_A_STAGES = {
    "a_sales": ("trade", ["order_sales_hourly"]),
    "a_prod": ("trade", ["product_sales_daily"]),
    "a_funnel": ("funnels", ["funnel_daily", "funnel_session_product"]),
    "a_rprod": ("reviews", ["review_product_daily"]),
    "a_raspect": ("reviews", ["review_aspect_daily"]),
}


def _flow_from_gold_a(now: pd.Timestamp) -> dict:
    """gold_a.gold_runs 에서 channel 별 마지막 완료 한 줄. available_tables_json = {표 이름: 행 수}."""
    df = _athena(
        "SELECT channel, run_id, completed_at, status, quality_status, available_tables_json FROM ("
        " SELECT *, row_number() OVER (PARTITION BY channel ORDER BY completed_at DESC) AS rn"
        " FROM gold_a.gold_runs) WHERE rn = 1"
    )
    last = {r.channel: r for r in df.itertuples()}
    out = {}
    for stage, (channel, tables) in _GOLD_A_STAGES.items():
        r = last.get(channel)
        if r is None:
            out[stage] = (
                "warn",
                "완료 기록 없음",
                f"gold_a.gold_runs 에 channel={channel} 행이 없습니다",
            )
            continue
        at = _utc(pd.Series([r.completed_at])).iloc[0]
        try:
            counts = json.loads(r.available_tables_json or "{}")
        except ValueError:
            counts = {}
        missing = [t for t in tables if t not in counts]
        rows_ = sum(int(counts.get(t) or 0) for t in tables)
        detail = f"channel {channel} · run {r.run_id} · 품질 {r.quality_status}\n{', '.join(tables)} {rows_:,}행"
        if missing:
            detail += f"\n이번 실행에 없음: {', '.join(missing)}"
        if r.status != "COMPLETED":
            status = "bad"
        elif missing or r.quality_status != "PASS" or (now - at).total_seconds() > FLOW_BATCH_WARN:
            status = "warn"
        else:
            status = "ok"
        out[stage] = (status, f"{_kst_hm(at)} 완료", detail)
    return out


def _flow_from_gold_b(now: pd.Timestamp) -> dict:
    """Gold B 원장 3개의 마지막 적재 시각(loaded_at). 오늘·어제 UTC 파티션만 읽는다."""
    days = f"dt IN ('{now:%Y-%m-%d}', '{now - pd.Timedelta(days=1):%Y-%m-%d}')"
    today = f"dt = '{now:%Y-%m-%d}'"
    df = _athena(
        " UNION ALL ".join(
            f"SELECT '{t}' AS t, max(loaded_at) AS last_at, count_if({today}) AS today_n"
            f" FROM gold_b.{t} WHERE {days}"
            for t in ("topic_messages", "payment_events", "malformed_events")
        )
    ).set_index("t")
    out = {}
    for stage, t in (("b_ledger", "topic_messages"), ("b_pay", "payment_events")):
        at = _utc(pd.Series([df.at[t, "last_at"]])).iloc[0]
        n = int(float(df.at[t, "today_n"] or 0))
        if pd.isna(at):
            out[stage] = (
                "warn",
                "이틀간 적재 없음",
                f"gold_b.{t} 오늘·어제 파티션이 비어 있습니다",
            )
            continue
        age = (now - at).total_seconds()
        out[stage] = (
            "warn" if age > FLOW_GOLD_B_WARN else "ok",
            _ago(age) + " 적재",
            f"오늘(UTC) {n:,}행 · gold_b.{t}",
        )
    # 형식 오류는 '있으면 문제'가 아니라 건수를 보여 주는 단계다. 자세한 건 형식 오류 화면에서 본다
    n = int(float(df.at["malformed_events", "today_n"] or 0))
    out["b_malformed"] = (
        "ok",
        f"오늘 {n:,}건",
        "gold_b.malformed_events · 원인은 형식 오류 화면에서 확인",
    )
    return out


def _flow_from_review_bronze(now: pd.Timestamp) -> dict:
    """S3 bronze/reviews/year=/month=/day=/ (UTC 날짜 폴더) 에서 가장 최근 도착 파일을 찾는다.
    리뷰는 Kafka 를 거치지 않으므로 지연 수집기로는 알 수 없고, Glue 표도 없어 S3 목록을 직접 본다.
    오늘부터 3일 전까지만 본다 (목록 요청 4번 안쪽)."""
    import boto3  # 실데이터를 쓸 때만 필요하다

    s3 = boto3.client("s3", region_name=AWS_REGION)
    for back in range(4):
        d = now - pd.Timedelta(days=back)
        prefix = f"bronze/reviews/year={d:%Y}/month={d:%m}/day={d:%d}/"
        objs = []
        for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=DATALAKE_BUCKET, Prefix=prefix
        ):
            objs += page.get("Contents", [])
        if objs:
            last = max(pd.Timestamp(o["LastModified"]) for o in objs)
            age = (now - last).total_seconds()
            size = sum(o["Size"] for o in objs) / 1024
            return {
                "r_bronze": (
                    "warn" if age > FLOW_REVIEW_WARN else "ok",
                    f"{_kst_hm(last)} 도착",
                    f"{prefix} · 파일 {len(objs)}개 · {size:,.0f}KB · 하루 1번(UTC 00:30) 생성",
                )
            }
    return {
        "r_bronze": (
            "warn",
            "4일간 도착 없음",
            "bronze/reviews/ 최근 4일 날짜 폴더가 비어 있습니다",
        )
    }


# 단계 묶음별 조회 함수. 한 묶음이 실패해도 다른 묶음은 그린다
_FLOW_READERS = [
    (_flow_from_lag, ["rds", "cdc", "collector", "kafka", "sink", "bronze"]),
    (_flow_from_review_bronze, ["r_bronze"]),
    (_flow_from_silver, ["s_trade"]),
    (_flow_from_gold_a, list(_GOLD_A_STAGES)),
    (_flow_from_gold_b, ["b_ledger", "b_pay", "b_malformed"]),
]


@st.cache_data(ttl=60, show_spinner=False)
def get_flow_status() -> dict:
    """흐름도 단계별 상태 {단계 id: (status, 원 아래 값, 마우스 올림 설명)} 와 조회 시각.

    status: ok / warn / bad / unknown(조회 실패·판단 불가). 여기 없는 단계는 화면이 '미연결'로 그린다.
    workgroup 이 없으면 아무것도 읽지 않는다 (= 전부 미연결).
    """
    now = pd.Timestamp.now(tz="UTC")
    stages: dict = {}
    if ATHENA_WORKGROUP:
        for reader, ids in _FLOW_READERS:
            try:
                got = reader(now)
                # 연결은 됐는데 값을 못 만든 단계는 '확인 불가'로 둔다 (미연결과 구분)
                stages |= {i: ("unknown", "확인 불가", "판단할 값이 없습니다") for i in ids} | got
            except Exception as e:  # noqa: BLE001  한 묶음 실패가 화면 전체를 죽이지 않게
                _log.exception("흐름도 조회 실패: %s", reader.__name__)
                stages |= {
                    i: ("unknown", "조회 실패", f"{type(e).__name__}: {str(e)[:160]}") for i in ids
                }
    return {"checked_at": now, "stages": stages}
