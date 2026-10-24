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
st.subheader("리뷰 수 · 별점")
rv = ui.last_days(data.get_review_product_daily(), "review_date_kst", days)
rv = rv[rv.article_id.isin(arts)]
ui.require_rows(rv)
cnt, rs, low = rv.review_count.sum(), rv.rating_sum.sum(), rv.low_rating_count.sum()
m = st.columns(3)
m[0].metric("리뷰 수", f"{int(cnt):,}")
m[1].metric("평균 별점", "계산 불가" if cnt == 0 else f"{rs / cnt:.2f}")
m[2].metric("낮은 별점(1~2점) 비율", ui.pct(low / cnt if cnt else float("nan")))
daily = rv.groupby("review_date_kst")[["review_count", "rating_sum", "low_rating_count"]].sum()
daily["average_rating"] = data.safe_div(daily.rating_sum, daily.review_count)
st.line_chart(daily[["review_count"]])

# ---- 속성 ----
st.subheader("속성별 부정 비율")
asp = ui.last_days(data.get_review_aspect_daily(), "review_date_kst", days)
asp = asp[asp.article_id.isin(arts)]
asp = ui.select_model(asp, "rv_model")
g = asp.groupby("aspect", as_index=False)[
    [
        "mentioned_review_count",
        "positive_review_count",
        "neutral_review_count",
        "negative_review_count",
    ]
].sum()
g["negative_rate"] = data.safe_div(g.negative_review_count, g.mentioned_review_count)
st.bar_chart(g.set_index("aspect")["negative_rate"])
st.dataframe(g.sort_values("negative_rate", ascending=False), hide_index=True, width="stretch")
st.caption("속성별 리뷰 수는 합쳐서 전체 리뷰 수로 쓰지 않습니다.")

# ---- 속성 추이 ----
one = st.selectbox("추이를 볼 속성", sorted(asp.aspect.dropna().unique()))
tr = (
    asp[asp.aspect == one]
    .groupby("review_date_kst")[["mentioned_review_count", "negative_review_count"]]
    .sum()
)
tr["negative_rate"] = data.safe_div(tr.negative_review_count, tr.mentioned_review_count)
st.line_chart(tr[["negative_rate"]])

st.info("근거 리뷰 원문 목록과 LLM 요약은 원문 조회 방식이 정해지면 이 아래에 추가합니다 (내부용).")
ui.dummy_note()
