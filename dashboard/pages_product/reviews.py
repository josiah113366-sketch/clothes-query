"""[상품 관리] 리뷰·속성 분석. 데이터: Gold A review_product_daily, review_aspect_daily.

주의 (노션):
  - 낮은 별점(1~2점)은 별점 기준이다. AI 가 판정한 '부정 감성'과 다르다.
  - 기간 평균 별점 = sum(rating_sum) ÷ sum(review_count). 일별 평균의 단순 평균이 아니다.
  - 속성별 리뷰 수는 합쳐서 전체 리뷰 수로 쓰지 않는다 (리뷰 하나가 여러 속성을 언급).
  - 서로 다른 model_version 을 섞어 하나의 비율로 만들지 않는다 -> 버전을 하나 골라서 본다.
  - 미분석·분석 실패 리뷰를 중립으로 처리하지 않는다 (이 표에는 분석된 것만 들어 있다).
나중에 추가할 것: 속성을 고르면 근거 리뷰 원문 목록(내부용. 원문은 외부 서비스로 보내지 않는다), LLM 요약.
"""

import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("product")
ui.begin_gold_page("reviews")

st.title("리뷰·속성 분석")
ui.date_note("review")
c1, c2 = st.columns([2, 1])
with c1:
    arts = ui.pick_products("rv")
with c2:
    days = ui.pick_period("rv")

# ---- 별점 ----
# 직전 같은 길이 기간(카드의 증감 배지)까지 쓰려고 2배 기간을 한 번에 읽는다
all_rv = data.get_review_product_daily(days * 2)
all_rv = all_rv[all_rv.article_id.isin(arts)]
rv = ui.last_days(all_rv, "review_date_kst", days)
ui.require_rows(rv)
prv = ui.prev_days(all_rv, "review_date_kst", days)
cnt, rs, low = rv.review_count.sum(), rv.rating_sum.sum(), rv.low_rating_count.sum()
pcnt, prs, plow = prv.review_count.sum(), prv.rating_sum.sum(), prv.low_rating_count.sum()
daily = rv.groupby("review_date_kst")[["review_count", "rating_sum", "low_rating_count"]].sum()
daily["average_rating"] = data.safe_div(daily.rating_sum, daily.review_count)
daily["low_rate"] = data.safe_div(daily.low_rating_count, daily.review_count)
note = f"직전 {days}일 대비"
ui.kpis(
    [
        {
            "label": "리뷰 수",
            "value": f"{int(cnt):,}",
            "unit": "건",
            "delta": ui.delta(cnt, pcnt),
            "good": None,
            "sub": note,
            "spark": daily.review_count,
        },
        {
            "label": "평균 별점",
            "value": "계산 불가" if cnt == 0 else f"{rs / cnt:.2f}",
            "unit": "/ 5",
            "delta": ui.delta(rs / cnt if cnt else None, prs / pcnt if pcnt else None),
            "good": "up",
            "sub": note,
            "spark": daily.average_rating,
        },
        {
            "label": "낮은 별점(1~2점) 비율",
            "value": ui.pct(low / cnt if cnt else float("nan")),
            "delta": ui.delta(low / cnt if cnt else None, plow / pcnt if pcnt else None),
            "good": "down",
            "sub": note,
            "spark": daily.low_rate,
        },
    ]
)
with ui.panel("일별 리뷰 수", "작성일(KST) 기준 · 건"):
    charts.bar(
        daily[["review_count"]], key="rv_cnt", labels={"review_count": "리뷰 수"}, height="240px"
    )

# ---- 속성 ----
asp = ui.last_days(data.get_review_aspect_daily(), "review_date_kst", days)
asp = asp[asp.article_id.isin(arts)]
asp = ui.select_model(asp, "rv_model")
# 고른 모델 버전 이름 (패널 제목에 표시). select_model 이 버전 하나만 남긴 표를 돌려준다
ver = asp["model_key" if "model_key" in asp else "model_version"].iloc[0]
g = asp.groupby("aspect", as_index=False)[
    [
        "mentioned_review_count",
        "positive_review_count",
        "neutral_review_count",
        "negative_review_count",
    ]
].sum()
g["negative_rate"] = data.safe_div(g.negative_review_count, g.mentioned_review_count)
g = g.sort_values("negative_rate", ascending=False)
with ui.panel("속성별 부정 비율", f"모델 버전 {ver} · 부정 비율 높은 순"):
    # 부정 비율 높은 순 진행 막대. 색은 한 가지(상태색이 아니라 계열 1색)로 크기만 비교한다.
    # 막대 끝 = 가장 높은 속성의 비율 (100% 가 아니다). 정확한 값은 막대 오른쪽 숫자로 읽는다.
    charts.rank(
        [(a, r, charts.color(0)) for a, r in zip(g.aspect, g.negative_rate, strict=True)],
        key="rv_neg",
        max_value=max(float(g.negative_rate.fillna(0).max()), 0.01),
    )
    with st.expander("표로 보기"):
        st.dataframe(g, hide_index=True, width="stretch")
    st.caption("속성별 리뷰 수는 합쳐서 전체 리뷰 수로 쓰지 않습니다.")

# ---- 속성 추이 ----
one = st.selectbox("추이를 볼 속성", sorted(asp.aspect.dropna().unique()))
tr = (
    asp[asp.aspect == one]
    .groupby("review_date_kst")[["mentioned_review_count", "negative_review_count"]]
    .sum()
)
tr["negative_rate"] = data.safe_div(tr.negative_review_count, tr.mentioned_review_count)
with ui.panel(f"{one} 부정 비율 추이", f"모델 버전 {ver} · 작성일(KST) 기준"):
    charts.line(
        tr[["negative_rate"]],
        key="rv_trend",
        fmt="pct",
        labels={"negative_rate": "부정 비율"},
        height="260px",
    )

st.info("근거 리뷰 원문 목록과 LLM 요약은 원문 조회 방식이 정해지면 이 아래에 추가합니다 (내부용).")
ui.dummy_note()
