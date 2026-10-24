"""[상품 관리] 상품 판매. 데이터: Gold A product_sales_daily (결제일 × 상품).

답할 질문: 어떤 상품 판매가 줄었나? 같은 디자인(product_code) 전체는 얼마나 팔렸나?
주의: 디자인별 '주문 수'는 상품별 주문 수를 단순 합산하지 않는다(한 주문에 같은 디자인의 여러 상품이
      들어갈 수 있음). 그래서 디자인 합계는 수량·금액만 보여준다. 금액은 취소·환불 차감 전.
"""

import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("product")

st.title("상품 판매")
ui.date_note("sales")
c1, c2 = st.columns([2, 1])
with c1:
    arts = ui.pick_products("ps")
with c2:
    days = ui.pick_period("ps")

all_df = data.get_product_sales_daily()
all_df = all_df[all_df.article_id.isin(arts)]
df = ui.last_days(all_df, "sales_date_kst", days)
prev = ui.prev_days(all_df, "sales_date_kst", days)
names = data.PRODUCTS.set_index("article_id")["name"]
dd = df.groupby("sales_date_kst")[["sold_quantity", "item_sales_amount"]].sum()
note = f"직전 {days}일 대비 · 고른 상품 {len(arts)}개"
ui.kpis(
    [
        {
            "label": "판매 수량",
            "value": f"{int(df.sold_quantity.sum()):,}",
            "unit": "개",
            "delta": ui.delta(df.sold_quantity.sum(), prev.sold_quantity.sum()),
            "good": "up",
            "sub": note,
            "spark": dd.sold_quantity,
        },
        {
            "label": "판매 금액",
            "value": f"{int(df.item_sales_amount.sum()):,}",
            "unit": "원",
            "delta": ui.delta(df.item_sales_amount.sum(), prev.item_sales_amount.sum()),
            "good": "up",
            "sub": note,
            "spark": dd.item_sales_amount,
        },
    ]
)

metric = st.radio(
    "지표",
    ["sold_quantity", "item_sales_amount"],
    horizontal=True,
    format_func={"sold_quantity": "판매 수량", "item_sales_amount": "판매 금액(원)"}.get,
)
pv = df.pivot(index="sales_date_kst", columns="article_id", values=metric)
# 색은 상품 목록 순서로 고정한다 (선택을 바꿔도 같은 상품은 같은 색). 7개 이상이면 색이 반복된다.
order = list(data.PRODUCTS.article_id)
pv = pv[[a for a in order if a in pv.columns]]
with ui.panel("상품별 추이", "결제일(KST) 기준"):
    charts.line(
        pv.rename(columns=names),
        key="ps_trend",
        fmt="won" if metric == "item_sales_amount" else None,
        colors=[charts.color(order.index(a)) for a in pv.columns],
        area=False,
    )

st.subheader("상품별 합계")
tot = df.groupby(["article_id", "product_code"], as_index=False)[
    ["sold_quantity", "item_sales_amount"]
].sum()
tot.insert(1, "name", tot.article_id.map(names))
st.dataframe(
    tot.sort_values("item_sales_amount", ascending=False), hide_index=True, width="stretch"
)

st.subheader("디자인(product_code)별 합계")
des = df.groupby("product_code", as_index=False)[["sold_quantity", "item_sales_amount"]].sum()
st.dataframe(des, hide_index=True, width="stretch")
st.caption("디자인별 주문 수는 상품별 주문 수의 합이 아니므로 여기서는 표시하지 않습니다.")
ui.dummy_note()
