"""[상품 관리] 구매 퍼널. 데이터: Gold A funnel_daily (+ 근거 상세 funnel_session_product).

답할 질문: 조회 자체가 줄었나? 조회는 유지되는데 담기·주문·결제 도달이 줄었나? 어느 단계 이탈이 늘었나?
주의 (노션):
  - 날짜는 결제일이 아니라 방문·상품의 '첫 조회일'이다.
  - 장바구니 미관찰 주문도 있으므로 (담기 - 주문)을 이탈 수로 쓰지 않는다.
    담기 이후 주문 미관찰 = cart_sessions - cart_order_sessions (최종 이탈로 단정하지 않는다).
  - 분모가 0 인 비율은 0%가 아니라 '계산 불가'.
"""

import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("product")
ui.begin_gold_page("funnels")

st.title("구매 퍼널")
ui.date_note("funnel")
c1, c2 = st.columns([2, 1])
with c1:
    arts = None
    if st.checkbox("상품별 필터 사용", value=False, key="fn_product_filter"):
        arts = ui.pick_products("fn")
        if "__gold_a_all_products__" in st.session_state.get("prod_fn", []):
            arts = None
    else:
        st.caption("전체 상품 · 날짜별 합계 조회")
with c2:
    days = ui.pick_period("fn")

if data.gold_a_real():
    with st.spinner("검증된 퍼널 집계 조회 중…"):
        df = data.gold_call("funnel_summary", days, arts)
else:
    df = ui.last_days(data.get_funnel_daily(), "funnel_date_kst", days)
    if arts is not None:
        df = df[df.article_id.isin(arts)]
ui.require_rows(df)
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
        "단위는 세션×상품이며 고유 고객·주문 수가 아닙니다. 담기→주문 연결 비율은 담은 뒤 주문이 관찰된 방문(cart_order_sessions) 기준입니다. 장바구니가 관찰되지 않은 주문도 포함될 수 있습니다."
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
            "sub": f"이후 주문 미관찰 {int(s.cart_sessions - s.cart_order_sessions):,} 방문",
        },
        {"label": "주문→결제", "value": ui.pct(rate(s.paid_sessions, s.order_sessions))},
    ]
)

with ui.panel("장바구니 관찰 여부별 주문", "동일 실행·첫 조회일(KST)·선택 상품의 세션×상품 기준"):
    if data.gold_a_real():
        from gold_a_io import GoldAError

        try:
            paths = data.gold_reader().funnel_order_paths(days, arts, s.to_dict())
        except GoldAError as error:
            st.info(str(error))
        else:
            st.dataframe([
                {"주문 경로": "장바구니 경유 주문", "도달 수": paths["cart_order_sessions"],
                 "전체 주문 대비": ui.pct(paths["cart_order_sessions"] / paths["order_sessions"])},
                {"주문 경로": "장바구니 미관찰 주문", "도달 수": paths["order_without_cart"],
                 "전체 주문 대비": ui.pct(paths["without_cart_rate"])},
            ], hide_index=True, width="stretch")
            st.caption(f"미관찰 주문 {paths['order_without_cart']:,} / 전체 주문 {paths['order_sessions']:,} = {paths['without_cart_rate']:.2%}")
            other = paths["order_with_cart"] - paths["cart_order_sessions"]
            if other:
                st.caption(f"장바구니는 관찰됐지만 담기 이후 주문 연결은 확인되지 않은 방문 {other:,}건은 경유 주문에 포함하지 않습니다.")
    else:
        st.info("주문 경로 분석 불가: 실제 Gold 상세 조회가 필요합니다.")
    st.caption("장바구니 미관찰만으로 바로 구매 또는 이벤트 누락이라고 단정할 수 없습니다. PARTIAL 범위의 관찰 결과이며, 이후 주문·결제 미관찰은 최종 이탈·결제 실패와 다릅니다.")

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
    if arts is None:
        st.info("방문별 상세는 상품별 필터에서 개별 상품을 선택하면 조회할 수 있습니다.")
    else:
        one = st.selectbox("상품", arts, key="fn_detail")
        st.dataframe(data.get_funnel_session_product(one), hide_index=True, width="stretch")
ui.dummy_note()
