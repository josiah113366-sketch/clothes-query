"""[상품 관리] 주문·매출. 데이터: Gold A order_sales_hourly (KST 1시간 단위, 전체 시간대 집계).

답할 질문: 주문 생성이 언제부터 줄었나? 주문은 유지되는데 결제 성공만 줄었나? 승인 금액도 줄었나?
주의: 상품별 시간대 분석은 이 표로 못 한다. 같은 시간의 paid_order_count ÷ order_count 를
      '구매 전환율'로 표시하지 않는다 (이전 시간 주문이 나중에 결제될 수 있음).
"""

import pandas as pd
import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("product")

st.title("주문·매출")
ui.date_note("hour")
days = ui.pick_period("ord", max_days=7, default=3)  # 더미는 7일치

all_hours = data.get_order_sales_hourly(7)
df = all_hours[all_hours.hour_start_kst > all_hours.hour_start_kst.max() - pd.Timedelta(days=days)]
# 직전 같은 길이 기간 (카드의 증감 배지). 더미가 7일치라 days 가 4 이상이면 비교 기간이 짧아진다.
prev = ui.prev_days(all_hours, "hour_start_kst", days)
d = df.set_index("hour_start_kst")
note = f"직전 {days}일 대비"
ui.kpis(
    [
        {
            "label": "주문 수",
            "value": f"{int(df.order_count.sum()):,}",
            "unit": "건",
            "delta": ui.delta(df.order_count.sum(), prev.order_count.sum()),
            "good": "up",
            "sub": note,
            "spark": d.order_count,
        },
        {
            "label": "결제 성공 주문 수",
            "value": f"{int(df.paid_order_count.sum()):,}",
            "unit": "건",
            "delta": ui.delta(df.paid_order_count.sum(), prev.paid_order_count.sum()),
            "good": "up",
            "sub": note,
            "spark": d.paid_order_count,
        },
        {
            "label": "승인 금액",
            "value": f"{int(df.approved_amount.sum()):,}",
            "unit": "원",
            "delta": ui.delta(df.approved_amount.sum(), prev.approved_amount.sum()),
            "good": "up",
            "sub": note,
            "spark": d.approved_amount,
        },
    ]
)

with ui.panel("주문 수 vs 결제 성공 주문 수", "KST 1시간 단위 · 건"):
    # 결제 성공은 점선: '보낸 것 vs 받은 것' 처럼 같은 흐름의 앞뒤를 겹쳐 본다
    charts.line(
        d[["order_count", "paid_order_count"]],
        key="ord_cnt",
        labels={"order_count": "주문", "paid_order_count": "결제 성공 주문"},
        dashed=("paid_order_count",),
    )
with ui.panel("승인 금액", "KST 1시간 단위"):
    charts.bar(
        d[["approved_amount"]], key="ord_amt", fmt="won", labels={"approved_amount": "승인 금액"}
    )
st.caption(
    "주문은 유지되는데 결제 성공·승인 금액만 줄었다면 Gold B 결제 기록(데이터 관리)에서 PG 실패를 함께 확인하세요."
)
ui.dummy_note()
