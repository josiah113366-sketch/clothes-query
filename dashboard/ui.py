"""여러 화면이 같이 쓰는 선택 위젯과 표시 도우미.

꾸미기(2026-10-24, streamlit-echarts 적용)
  style() : 앱 전체 CSS (지표 카드, 패널, 제목). app.py 가 한 번 부른다.
  kpis()  : 지표 카드 한 줄 (색 띠 + 값 + 증감 배지 + 작은 추이선). st.metric 대신 쓴다.
  panel() : 둥근 테두리 패널 (제목 + 오른쪽 작은 설명). with ui.panel("제목"): 안에 내용을 넣는다.
  delta() : 이번 기간과 직전 같은 길이 기간의 변화율.
색은 charts.PALETTE(계열)와 GOOD/WARN/BAD(상태)를 쓴다. 바탕색은 .streamlit/config.toml [theme].
"""

import html
import math

import pandas as pd
import streamlit as st

import charts
import data

# 기간 선택 기본값(일). 화면 성격에 맞게 바꿔도 된다.
DEFAULT_DAYS = 14


def pick_period(key: str, max_days: int = 30, default: int = DEFAULT_DAYS) -> int:
    """최근 N일 선택. 더미 데이터가 30일치라 최대 30. 실데이터 연결 후 늘려도 된다."""
    return st.slider("조회 기간(최근 N일)", 3, max_days, default, key=f"days_{key}")


def pick_products(key: str, multi: bool = True) -> list[str]:
    """상품(article_id) 선택. 이름 + article_id 로 보여주고 article_id 목록을 돌려준다.

    상품별 통합 조회는 article_id 기준이다 (노션). product_code 는 '디자인 묶음' 기준이다.
    """
    p = data.PRODUCTS
    labels = {r.article_id: f"{r['name']} ({r.article_id})" for _, r in p.iterrows()}
    if multi:
        picked = st.multiselect(
            "상품", list(labels), default=list(labels), format_func=labels.get, key=f"prod_{key}"
        )
    else:
        picked = [st.selectbox("상품", list(labels), format_func=labels.get, key=f"prod_{key}")]
    return picked


def last_days(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """date 컬럼 기준 최근 N일만 남긴다."""
    return df[df[col] > df[col].max() - pd.Timedelta(days=days)]


def prev_days(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """last_days 바로 앞의 같은 길이 기간 (카드의 '직전 기간 대비' 계산용). 없으면 빈 표."""
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
    st.caption("※ 현재는 더미 데이터입니다. 금액은 취소·환불 차감 전 값입니다.")


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
    box.markdown(
        f'<div class="panel-h"><span class="panel-t">{html.escape(title)}</span>'
        f'<span class="panel-n">{html.escape(note)}</span></div>',
        unsafe_allow_html=True,
    )
    return box
