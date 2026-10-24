"""[상품 관리] 주문·매출. 데이터: Gold A order_sales_hourly (KST 1시간 단위, 전체 시간대 집계).

답할 질문: 주문 생성이 언제부터 줄었나? 주문은 유지되는데 결제 성공만 줄었나? 승인 금액도 줄었나?
주의: 상품별 시간대 분석은 이 표로 못 한다. 같은 시간의 paid_order_count ÷ order_count 를
      '구매 전환율'로 표시하지 않는다 (이전 시간 주문이 나중에 결제될 수 있음).
"""

import streamlit as st

import data
import ui
from auth import require_role

require_role("product")
ui.begin_gold_page("trade")

st.title("주문·매출")
ui.date_note("hour")
days = ui.pick_period("ord", max_days=7, default=3)  # 더미는 7일치

df = ui.last_days(data.get_order_sales_hourly(days), "hour_start_kst", days)
ui.require_rows(df)

a, b, c = st.columns(3)
a.metric("주문 수", f"{int(df.order_count.sum()):,}")
b.metric("결제 성공 주문 수", f"{int(df.paid_order_count.sum()):,}")
c.metric("승인 금액(원)", f"{int(df.approved_amount.sum()):,}")

d = df.set_index("hour_start_kst")
st.subheader("주문 수 vs 결제 성공 주문 수")
st.line_chart(d[["order_count", "paid_order_count"]])
st.subheader("승인 금액")
st.bar_chart(d["approved_amount"])
st.caption(
    "주문은 유지되는데 결제 성공·승인 금액만 줄었다면 Gold B 결제 기록(데이터 관리)에서 PG 실패를 함께 확인하세요."
)
ui.dummy_note()
