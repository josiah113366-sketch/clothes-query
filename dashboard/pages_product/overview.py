"""[상품 관리] 통합 조회. 상품과 기간을 한 번 고르면 관련 결과를 한 화면에 모은다.

노션 'Gold A 설계 정리' 7장의 화면 영역 6개를 그대로 따랐다.
  판매 / 구매 흐름 / 리뷰 / 불만 범주 / 관련 장애 / 데이터 상태
주의 (노션): 지표가 같은 시기에 변한 것은 '조사 단서'일 뿐 원인으로 단정하지 않는다.
        집계 단위가 다른 테이블을 그대로 조인하지 않는다 (금액·건수가 반복됨) -> 영역마다 따로 집계해서 보여준다.
"""

import streamlit as st

import data
import ui
from auth import require_role

require_role("product")

st.title("통합 조회")
st.caption("같은 시기에 함께 변한 지표는 조사 단서입니다. 원인으로 단정하지 마세요.")

c1, c2 = st.columns([2, 1])
with c1:
    art = ui.pick_products("ov", multi=False)
with c2:
    days = ui.pick_period("ov")

# ---- 판매 (결제일) ----
st.subheader("판매")
ui.date_note("sales")
sales = ui.last_days(data.get_product_sales_daily(), "sales_date_kst", days)
sales = sales[sales.article_id.isin(art)]
m1, m2 = st.columns(2)
m1.metric("판매 수량", f"{int(sales.sold_quantity.sum()):,}")
m2.metric("상품 판매 금액(원)", f"{int(sales.item_sales_amount.sum()):,}")
st.line_chart(sales.set_index("sales_date_kst")[["sold_quantity"]])

# ---- 구매 흐름 (첫 조회일) ----
st.subheader("구매 흐름")
ui.date_note("funnel")
fn = ui.last_days(data.get_funnel_daily(), "funnel_date_kst", days)
fn = fn[fn.article_id.isin(art)]
v = fn[["view_sessions", "cart_sessions", "order_sessions", "paid_sessions"]].sum()
f1, f2, f3, f4 = st.columns(4)
f1.metric("조회", f"{int(v.view_sessions):,}")
f2.metric("담기", f"{int(v.cart_sessions):,}")
f3.metric("주문", f"{int(v.order_sessions):,}")
f4.metric("결제", f"{int(v.paid_sessions):,}")
# 기간 전환율은 일별 비율의 평균이 아니라 합계끼리 다시 나눈다 (분모 0 이면 계산 불가)
st.caption(
    f"조회→결제 전환율: {ui.pct(v.paid_sessions / v.view_sessions if v.view_sessions else float('nan'))}"
)

# ---- 리뷰 (작성일) ----
st.subheader("리뷰")
ui.date_note("review")
rv = ui.last_days(data.get_review_product_daily(), "review_date_kst", days)
rv = rv[rv.article_id.isin(art)]
cnt, rs, low = rv.review_count.sum(), rv.rating_sum.sum(), rv.low_rating_count.sum()
r1, r2, r3 = st.columns(3)
r1.metric("리뷰 수", f"{int(cnt):,}")
r2.metric("평균 별점", "계산 불가" if cnt == 0 else f"{rs / cnt:.2f}")  # 합계/합계로 재계산
r3.metric("낮은 별점(1~2점) 비율", ui.pct(low / cnt if cnt else float("nan")))
st.caption("낮은 별점은 별점 기준이며 AI가 판정한 부정 감성과 다릅니다.")

# ---- 불만 범주 (작성일) ----
st.subheader("불만 범주")
asp = ui.last_days(data.get_review_aspect_daily(), "review_date_kst", days)
asp = asp[asp.article_id.isin(art)]
g = asp.groupby("aspect", as_index=False)[["mentioned_review_count", "negative_review_count"]].sum()
g["negative_rate"] = data.safe_div(g.negative_review_count, g.mentioned_review_count)
st.dataframe(g.sort_values("negative_rate", ascending=False), hide_index=True, width="stretch")
st.caption(
    "속성별 리뷰 수는 합쳐서 전체 리뷰 수로 쓰지 않습니다(리뷰 하나가 여러 속성을 언급). "
    "모델 버전: " + ", ".join(data.MODEL_VERSIONS)
)

# ---- 관련 장애 (Gold B 기록, 같은 기간) ----
st.subheader("관련 장애")
an = data.get_anomalies().copy()
an["detected_at(KST)"] = data.to_kst(an.detected_at)
st.dataframe(an.drop(columns="detected_at"), hide_index=True, width="stretch")
st.caption(
    "Gold B의 장애 기록입니다. 같은 기간에 겹친다고 판매 변화의 원인이라고 단정하지 않습니다."
)

# ---- 데이터 상태 ----
st.subheader("데이터 상태")
st.dataframe(data.get_data_status(), hide_index=True, width="stretch")
st.caption("처리 완료 범위 밖의 낮은 값은 판매 감소가 아니라 데이터 지연일 수 있습니다.")
ui.dummy_note()
