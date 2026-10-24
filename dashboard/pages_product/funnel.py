"""[상품 관리] 구매 퍼널. 데이터: Gold A funnel_daily (+ 근거 상세 funnel_session_product).

답할 질문: 조회 자체가 줄었나? 조회는 유지되는데 담기·주문·결제 도달이 줄었나? 어느 단계 이탈이 늘었나?
주의 (노션):
  - 날짜는 결제일이 아니라 방문·상품의 '첫 조회일'이다.
  - 장바구니 없이 바로 주문하는 방문이 있으므로 (담기 - 주문) 을 이탈 수로 쓰지 않는다.
    담기 후 이탈 = cart_sessions - cart_order_sessions.
  - 분모가 0 인 비율은 0%가 아니라 '계산 불가'.
"""

import streamlit as st

import charts
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


# 기간 전환율은 일별 비율을 평균내지 않고 합계끼리 나눈다
def rate(n, d):
    return float("nan") if d == 0 else n / d


# 단계별 방문 수 (기간 합계). 단계 사이 글자 = 앞 단계 대비 비율
with ui.panel("단계별 도달 방문 수", "첫 조회일(KST) 기준 · 기간 합계"):
    charts.flow(
        [
            ("조회", s.view_sessions, f"{int(s.view_sessions):,}"),
            ("담기", s.cart_sessions, f"{int(s.cart_sessions):,}"),
            ("주문", s.order_sessions, f"{int(s.order_sessions):,}"),
            ("결제", s.paid_sessions, f"{int(s.paid_sessions):,}"),
        ],
        notes=[
            f"조회의 {ui.pct(rate(s.cart_sessions, s.view_sessions))}",
            f"담기의 {ui.pct(rate(s.cart_order_sessions, s.cart_sessions))} 주문",
            f"주문의 {ui.pct(rate(s.paid_sessions, s.order_sessions))}",
        ],
        key="fn_flow",
    )
    st.caption(
        "담기→주문 비율은 담은 뒤 주문한 방문(cart_order_sessions) 기준입니다. 장바구니 없이 바로 주문한 방문이 있어 담기 수보다 주문 수가 클 수 있습니다."
    )

daily = df.groupby("funnel_date_kst")[["paid_sessions", "view_sessions"]].sum()
daily["view_to_paid_rate"] = data.safe_div(daily.paid_sessions, daily.view_sessions)
ui.kpis(
    [
        {"label": "조회→담기", "value": ui.pct(rate(s.cart_sessions, s.view_sessions))},
        {"label": "조회→주문", "value": ui.pct(rate(s.order_sessions, s.view_sessions))},
        {
            "label": "조회→결제",
            "value": ui.pct(rate(s.paid_sessions, s.view_sessions)),
            "spark": daily.view_to_paid_rate,
            "sub": "일별 추이",
        },
        {
            "label": "담기→주문",
            "value": ui.pct(rate(s.cart_order_sessions, s.cart_sessions)),
            "sub": f"담기 후 이탈 {int(s.cart_sessions - s.cart_order_sessions):,} 방문",
        },
        {"label": "주문→결제", "value": ui.pct(rate(s.paid_sessions, s.order_sessions))},
    ]
)

with ui.panel("일별 조회→결제 전환율", "첫 조회일(KST) 기준"):
    charts.line(
        daily[["view_to_paid_rate"]],
        key="fn_rate",
        fmt="pct",
        labels={"view_to_paid_rate": "조회→결제 전환율"},
        height="260px",
    )

# 근거 상세: 방문별로 어디까지 진행했는지
with st.expander("근거: 방문별 진행 단계 (funnel_session_product)"):
    one = st.selectbox("상품", arts, key="fn_detail")
    st.dataframe(data.get_funnel_session_product(one), hide_index=True, width="stretch")
ui.dummy_note()
