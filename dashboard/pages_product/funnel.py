"""[상품 관리] 구매 퍼널. 데이터: Gold A funnel_daily (+ 근거 상세 funnel_session_product).

답할 질문: 조회 자체가 줄었나? 조회는 유지되는데 담기·주문·결제 도달이 줄었나? 어느 단계 이탈이 늘었나?
주의 (노션):
  - 날짜는 결제일이 아니라 방문·상품의 '첫 조회일'이다.
  - 장바구니 없이 바로 주문하는 방문이 있으므로 (담기 - 주문) 을 이탈 수로 쓰지 않는다.
    담기 후 이탈 = cart_sessions - cart_order_sessions.
  - 분모가 0 인 비율은 0%가 아니라 '계산 불가'.
"""

import streamlit as st

import data
import ui
from auth import require_role

require_role("product")

st.title("구매 퍼널")
ui.date_note("funnel")
c1, c2 = st.columns([2, 1])
with c1:
    arts = ui.pick_products("fn")
with c2:
    days = ui.pick_period("fn")

df = ui.last_days(data.get_funnel_daily(), "funnel_date_kst", days)
df = df[df.article_id.isin(arts)]
s = df[
    ["view_sessions", "cart_sessions", "order_sessions", "paid_sessions", "cart_order_sessions"]
].sum()

# 단계별 방문 수 (기간 합계)
st.subheader("단계별 도달 방문 수")
st.bar_chart(s[["view_sessions", "cart_sessions", "order_sessions", "paid_sessions"]])


# 기간 전환율은 일별 비율을 평균내지 않고 합계끼리 나눈다
def rate(n, d):
    return float("nan") if d == 0 else n / d


r = st.columns(5)
r[0].metric("조회→담기", ui.pct(rate(s.cart_sessions, s.view_sessions)))
r[1].metric("조회→주문", ui.pct(rate(s.order_sessions, s.view_sessions)))
r[2].metric("조회→결제", ui.pct(rate(s.paid_sessions, s.view_sessions)))
r[3].metric("담기→주문", ui.pct(rate(s.cart_order_sessions, s.cart_sessions)))
r[4].metric("주문→결제", ui.pct(rate(s.paid_sessions, s.order_sessions)))
st.caption(
    f"담기 후 이탈 방문 수 = {int(s.cart_sessions - s.cart_order_sessions):,} (cart_sessions - cart_order_sessions)"
)

st.subheader("일별 조회→결제 전환율")
daily = df.groupby("funnel_date_kst")[["paid_sessions", "view_sessions"]].sum()
daily["view_to_paid_rate"] = data.safe_div(daily.paid_sessions, daily.view_sessions)
st.line_chart(daily["view_to_paid_rate"])

# 근거 상세: 방문별로 어디까지 진행했는지
with st.expander("근거: 방문별 진행 단계 (funnel_session_product)"):
    one = st.selectbox("상품", arts, key="fn_detail")
    st.dataframe(data.get_funnel_session_product(one), hide_index=True, width="stretch")
ui.dummy_note()
