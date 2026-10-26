"""여러 화면이 같이 쓰는 선택 위젯과 표시 도우미.

꾸미기(2026-10-24, streamlit-echarts 적용)
  style() : 앱 전체 CSS (지표 카드, 패널, 제목). app.py 가 한 번 부른다.
  kpis()  : 지표 카드 한 줄 (색 띠 + 값 + 증감 배지 + 작은 추이선). st.metric 대신 쓴다.
  panel() : 둥근 테두리 패널 (제목 + 오른쪽 작은 설명). with ui.panel("제목"): 안에 내용을 넣는다.
  delta() : 이번 기간과 직전 같은 길이 기간의 변화율.
색은 charts.PALETTE(계열)와 GOOD/WARN/BAD(상태)를 쓴다. 바탕색은 .streamlit/config.toml [theme].
"""

import datetime
import html
import math
from typing import NamedTuple

import pandas as pd
import streamlit as st

import charts
import data

# 기간 선택 기본값(일). 화면 성격에 맞게 바꿔도 된다.
DEFAULT_DAYS = 14


def begin_gold_page(*channels):
    """화면을 다시 실행할 때 업무별 완료 실행을 한 번만 선택한다."""
    st.session_state.pop("_gold_a_reader", None)
    st.session_state.pop("_gold_a_context", None)
    st.session_state["_gold_a_channels"] = channels
    if not data.gold_a_real():
        st.warning("Gold A 미리보기: 더미 데이터입니다.")
        return
    mode = st.sidebar.radio("Gold 조회 모드", ["운영", "시연·검증"],
                            index=1 if st.session_state.get("_gold_a_mode") == "demo" else 0,
                            key="gold_a_view_mode")
    st.session_state["_gold_a_mode"] = "demo" if mode == "시연·검증" else "operation"
    st.session_state["_gold_a_selected_runs"] = {}
    if mode == "시연·검증":
        st.warning("시연·검증 모드: 실행별 검증 결과입니다. 전체 운영 데이터 완료를 의미하지 않습니다.")
        if "trade" in channels:
            options = data.gold_call("run_options", "trade")
            if not options.empty:
                labels = {r.run_id: f"{r.run_id} · {r.quality_status}" for r in options.itertuples()}
                chosen = st.sidebar.selectbox("거래 Gold 실행", list(labels), format_func=labels.get)
                st.session_state["_gold_a_selected_runs"] = {"trade": chosen}
        # Discard the options reader so selected run IDs are applied to all metrics.
        st.session_state.pop("_gold_a_reader", None)
    st.session_state["_gold_a_context"] = []
    st.caption("데이터 출처: AWS Athena Gold A 실행별 지표·보류 테이블. 시연 퍼널은 S3 checkpoint·완료 manifest도 대조합니다.")
    for channel in channels:
        run = data.gold_call("run", channel)
        if not run:
            st.info(f"{channel}: 아직 공개된 완료 실행이 없습니다.")
            continue
        st.caption(
            f"{channel} · 실행 {run['run_id']} · 기록 시각 {run['completed_at']} · {run['quality_status']}"
        )
        scope = run.get("scope", "공개 실행 범위; 전체 원천 처리 범위 미검증")
        st.caption(scope)
        context = f"{channel} / {run['run_id']} / {run['quality_status']} / {scope} / 기록 {run['completed_at']}"
        st.session_state["_gold_a_context"].append(context)
        if run["quality_status"] == "PARTIAL":
            st.warning(f"{channel}: PARTIAL — 부분 데이터 기준 지표·전환율입니다. 정상 완료된 전체 결과가 아닙니다.")
        if run.get("source_manifest"):
            st.caption(f"출처: {run['source_manifest']} · 확인: {run.get('verification_query_id', 'Athena 공개 완료 목록')}")
        if run.get("silver_run_id"):
            st.caption(f"기준 Silver 실행: {run['silver_run_id']}")
        holds = data.gold_call("holds", channel)
        if not holds.empty:
            st.info("보류 범위의 신규 오류 데이터는 집계에 반영하지 않습니다. 이전 정상 결과가 있으면 그 값을 유지하고, 없으면 제외합니다. 퍼널 백필 미처리는 아직 읽지 않은 범위입니다.")
            st.warning(
                f"{channel}: 갱신 보류 {len(holds)}개. 이전 정상 결과가 유지된 범위와 결과가 없는 범위를 확인하세요."
            )
            with st.expander(f"{channel} 갱신 보류 범위"):
                st.dataframe(holds, hide_index=True, width="stretch")


def has_rows(df):
    if not df.empty:
        return True
    message = {
        "NO_RUN": "아직 공개된 완료 실행이 없습니다.",
        "NOT_REQUESTED": "이 실행에서는 감성분석 결과를 제공하지 않았습니다.",
    }.get(df.attrs.get("state"), "선택한 기간·상품의 결과가 없습니다. 0건으로 판정하지 않습니다.")
    st.info(message)
    return False


def require_rows(df):
    if not has_rows(df):
        st.stop()


def select_model(df, key):
    require_rows(df)
    column = "model_key" if "model_key" in df else "model_version"
    chosen = st.selectbox("모델 버전", sorted(df[column].dropna().unique()), key=key)
    return df[df[column] == chosen]


def pick_period(key: str, max_days: int = 30, default: int = DEFAULT_DAYS) -> int:
    """최근 N일 선택. 더미 데이터가 30일치라 최대 30. 실데이터 연결 후 늘려도 된다."""
    return st.slider("조회 기간(최근 N일)", 3, max_days, default, key=f"days_{key}")


class Window(NamedTuple):
    """Gold B 화면의 조회 구간 (pick_window 결과). 조회 함수에는 (길이, end) 로 넘긴다."""

    hours: int  # 길이(시간)
    end: pd.Timestamp | None  # 끝(UTC). None = 지금까지 (실시간)
    label: str  # 화면 문구. 예: "최근 3시간", "10-25 15:00~17:00 KST"

    @property
    def minutes(self) -> int:
        return self.hours * 60


def pick_window(key: str, default_hours: int, max_hours: int = 24, history_days: int = 30) -> Window:
    """Gold B 화면(파이프라인 상태 › 지연·점검, 결제 관제, 형식 오류)의 조회 구간 (TODO B11, 2026-10-26).

    최근     : 최근 N시간(1 ~ max_hours). 지금까지라 화면을 다시 읽을 때마다 새 값이 보인다.
    날짜 지정: KST 날짜(최근 history_days 일) + 시간 범위(0~24시, 최대 하루). 지나간 시간대를 다시 본다.
              끝이 지금보다 늦으면 지금까지만 있다. 자정을 넘는 구간은 날짜를 나눠 본다.
    """
    mode_col, pick_col = st.columns([1, 3], vertical_alignment="bottom")
    mode = mode_col.radio("조회 구간", ["최근", "날짜 지정"], horizontal=True, key=f"win_{key}")
    if mode == "최근":
        hours = pick_col.slider("최근 N시간", 1, max_hours, default_hours, key=f"win_{key}_hours")
        return Window(hours, None, f"최근 {hours}시간")
    now = pd.Timestamp.now(tz="Asia/Seoul")
    today = now.date()
    day_col, hour_col = pick_col.columns([1, 2])
    day = day_col.date_input(
        "날짜(KST)",
        value=today,
        min_value=today - datetime.timedelta(days=history_days),
        max_value=today,
        key=f"win_{key}_day",
    )
    first, last = hour_col.slider("시간(KST)", 0, 24, (0, 24), format="%d시", key=f"win_{key}_range")
    if first == last:  # 같은 시각을 고르면 그 시각부터 한 시간
        first, last = (first, first + 1) if first < 24 else (23, 24)
    midnight = pd.Timestamp(day).tz_localize("Asia/Seoul")
    start, end = midnight + pd.Timedelta(hours=first), midnight + pd.Timedelta(hours=last)
    if start >= now:
        st.info("아직 오지 않은 시간입니다. 지금보다 앞선 시간을 고르세요.")
        st.stop()
    label = f"{day:%m-%d} {first:02d}:00~{last:02d}:00 KST" + (" (지금까지)" if end > now else "")
    return Window(last - first, end.tz_convert("UTC"), label)


def pick_products(key: str, multi: bool = True) -> list[str]:
    """상품(article_id) 선택. 이름 + article_id 로 보여주고 article_id 목록을 돌려준다.

    상품별 통합 조회는 article_id 기준이다 (노션). product_code 는 '디자인 묶음' 기준이다.
    """
    p = data.product_options()
    labels = {r.article_id: f"{r['name']} ({r.article_id})" for _, r in p.iterrows()}
    if not labels:
        st.info("공개 결과에 조회할 상품이 없습니다.")
        st.stop()
    if multi:
        # Keep the same all-products calculation without rendering tens of
        # thousands of selected chips for a real funnel snapshot.
        all_products = "__gold_a_all_products__"
        picked = st.multiselect(
            "상품", [all_products, *labels], default=[all_products],
            format_func=lambda value: "전체 상품" if value == all_products else labels[value],
            help="전체 상품을 해제하면 개별 상품을 선택할 수 있습니다.", key=f"prod_{key}"
        )
        if not picked:
            st.info("조회할 상품을 하나 이상 선택하세요.")
            st.stop()
        if all_products in picked:
            return list(labels)
    else:
        picked = [st.selectbox("상품", list(labels), format_func=labels.get, key=f"prod_{key}")]
    return picked


def last_days(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """date 컬럼 기준 최근 N일만 남긴다."""
    if data.gold_a_real():
        start = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize() - pd.Timedelta(
            days=days - 1
        )
        return df[df[col] >= start]
    return df[df[col] > df[col].max() - pd.Timedelta(days=days)]


def prev_days(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """last_days 바로 앞의 같은 길이 기간 (카드의 '직전 기간 대비' 계산용). 없으면 빈 표.
    last_days 와 같은 기준을 쓴다: 실데이터(Gold A Athena)는 오늘(KST), 더미는 데이터의 마지막 날."""
    if data.gold_a_real():
        start = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize() - pd.Timedelta(
            days=days - 1
        )
        return df[(df[col] < start) & (df[col] >= start - pd.Timedelta(days=days))]
    end = df[col].max() - pd.Timedelta(days=days)
    return df[(df[col] <= end) & (df[col] > end - pd.Timedelta(days=days))]


def pct(x: float) -> str:
    """비율 표시. NaN(= 분모 0, 계산 불가)은 0%가 아니라 '계산 불가'로 보여준다."""
    return "계산 불가" if pd.isna(x) else f"{x:.1%}"


def date_note(kind: str) -> None:
    """차트 날짜의 의미를 항상 표시한다 (노션: 판매=결제일, 퍼널=첫 조회일, 리뷰=작성일)."""
    note = {
        "sales": "결제일(KST) 기준",
        "funnel": "첫 조회일(KST) 기준",
        "review": "리뷰 작성일(KST) 기준",
        "hour": "KST 1시간 단위",
    }[kind]
    st.caption(f"📅 날짜 기준: {note}")


def dummy_note() -> None:
    source = "Athena 완료 실행 조회" if data.gold_a_real() else "더미 데이터"
    st.caption(f"※ {source}. 금액은 취소·환불 차감 전 값입니다.")


# ---------------------------------------------------------------- 꾸미기

# 앱 전체 CSS. 색은 config.toml [theme] 과 charts.py 의 값에 맞췄다. 바꾸면 세 곳을 같이 본다.
#   .kpi       : 지표 카드 (왼쪽 색 띠는 카드마다 --c 로 준다)
#   .kpi-badge : 증감 배지 (좋아짐 초록 / 나빠짐 빨강 / 판단 없음 회색)
#   stMetric   : 아직 st.metric 을 쓰는 화면도 카드처럼 보이게 한다
#   st.container(border=True) : 패널 (둥근 모서리, 옅은 테두리)
_CSS = """
<style>
.block-container {padding-top: 2.2rem;}
h1 {font-size: 1.55rem !important; font-weight: 700 !important;}
.kpi {background: #16181d; border: 1px solid #262a31; border-left: 3px solid var(--c);
      border-radius: 14px; padding: 12px 16px 0; overflow: hidden; margin-bottom: 14px;}
.kpi-l {font-size: 13px; color: #a7abb3; display: flex; align-items: center; gap: 6px;}
.kpi-v {font-size: 28px; font-weight: 700; line-height: 1.25; margin-top: 2px; color: #f1f2f4;}
.kpi-u {font-size: 14px; color: #a7abb3; font-weight: 400; margin-left: 2px;}
.kpi-s {font-size: 12px; color: #7d828b; min-height: 16px;}
.kpi svg, .kpi-nospark {display: block; margin: 6px -16px 0; width: calc(100% + 32px);
      height: 40px;}
.kpi-badge {font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 6px;}
.kpi-up {background: #3ddc9724; color: #3ddc97;}
.kpi-down {background: #ff5c7424; color: #ff6b81;}
.kpi-flat {background: #8b909924; color: #a7abb3;}
.panel-h {display: flex; justify-content: space-between; align-items: baseline; margin: -2px 0 6px;}
.panel-t {font-size: 15px; font-weight: 600; color: #e6e7ea;}
.panel-n {font-size: 12px; color: #7d828b;}
[data-testid="stMetric"] {background: #16181d; border: 1px solid #262a31; border-radius: 14px;
      padding: 12px 16px;}
[data-testid="stMetricLabel"] {color: #a7abb3;}
[data-testid="stMetricValue"] {font-size: 26px; font-weight: 700;}
h2 {font-size: 1.25rem !important;} h3 {font-size: 1.1rem !important;}
</style>
"""


def style() -> None:
    st.session_state.pop("_gold_a_context", None)
    st.markdown(_CSS, unsafe_allow_html=True)


def delta(cur: float, prev: float) -> float | None:
    """변화율 (cur - prev) / prev. 직전 값이 0 이거나 없으면 None (배지를 표시하지 않음)."""
    if prev is None or cur is None or pd.isna(prev) or pd.isna(cur) or prev == 0:
        return None
    return (cur - prev) / abs(prev)


def _spark(values, c: str) -> str:
    """작은 추이선 SVG (선 + 아래 그라데이션). 값이 2개 미만이면 빈 문자열."""
    v = [float(x) for x in pd.Series(values).tolist() if x is not None and not pd.isna(x)]
    if len(v) < 2:
        return ""
    lo, hi = min(v), max(v)
    span = (hi - lo) or 1.0
    w, h = 200, 40
    pts = [(i * w / (len(v) - 1), h - 3 - (x - lo) / span * (h - 8)) for i, x in enumerate(v)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    gid = f"g{abs(hash((line, c))) % 10**8}"
    return (
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{c}" stop-opacity=".35"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="0,{h} {line} {w},{h}" fill="url(#{gid})"/>'
        f'<polyline points="{line}" fill="none" stroke="{c}" stroke-width="1.6" '
        f'vector-effect="non-scaling-stroke"/></svg>'
    )


def kpis(cards: list[dict]) -> None:
    """지표 카드 한 줄. cards 의 각 항목:

    label  : 이름 (필수)
    value  : 표시할 값 문자열 (필수, 이미 형식을 맞춘 것. 예: "1,234", "계산 불가")
    unit   : 값 옆 작은 단위 (예: "원", "/분")
    delta  : 변화율 (ui.delta 결과, 0.21 = +21%). None 이면 배지 없음
    good   : "up"(늘면 좋음) / "down"(줄면 좋음) / None(좋고 나쁨 없음, 회색). 배지 색만 정한다
    sub    : 아래 작은 설명 (예: "직전 3일 대비", "누적 63,390")
    spark  : 작은 추이선 값 목록 (없으면 생략)
    color  : 왼쪽 띠·추이선 색. 없으면 카드 순서대로 charts.PALETTE
    배지는 ▲▼ 글자와 부호를 같이 보여 주므로 색만으로 판단하지 않는다.
    """
    for context in st.session_state.get("_gold_a_context", []):
        st.caption(context)
    cols = st.columns(len(cards))
    nospark = '<div class="kpi-nospark"></div>'
    for i, (col, c) in enumerate(zip(cols, cards, strict=True)):
        colr = c.get("color") or charts.color(i)
        badge = ""
        d = c.get("delta")
        if d is not None and not (isinstance(d, float) and math.isnan(d)):
            good = c.get("good")
            if abs(d) < 0.005 or good is None:
                cls = "kpi-flat"
            else:
                cls = "kpi-up" if (d > 0) == (good == "up") else "kpi-down"
            arrow = "▲" if d > 0 else "▼" if d < 0 else "•"
            badge = f'<span class="kpi-badge {cls}">{arrow} {abs(d):.0%}</span>'
        unit = f'<span class="kpi-u">{html.escape(c["unit"])}</span>' if c.get("unit") else ""
        col.markdown(
            f'<div class="kpi" style="--c:{colr}">'
            f'<div class="kpi-l">{html.escape(c["label"])}{badge}</div>'
            f'<div class="kpi-v">{html.escape(str(c["value"]))}{unit}</div>'
            f'<div class="kpi-s">{html.escape(c.get("sub") or "")}</div>'
            # 추이선이 없는 카드도 같은 높이가 되게 빈 칸을 둔다
            f"{(_spark(c['spark'], colr) if c.get('spark') is not None else '') or nospark}</div>",
            unsafe_allow_html=True,
        )


def panel(title: str, note: str = ""):
    """둥근 테두리 패널. 사용: with ui.panel("제목", "오른쪽 설명"): ...

    st.container(border=True) 를 돌려주므로 with 블록 안의 모든 요소가 패널 안에 들어간다.
    """
    box = st.container(border=True)
    for context in st.session_state.get("_gold_a_context", []):
        box.caption(context)
    box.markdown(
        f'<div class="panel-h"><span class="panel-t">{html.escape(title)}</span>'
        f'<span class="panel-n">{html.escape(note)}</span></div>',
        unsafe_allow_html=True,
    )
    return box
