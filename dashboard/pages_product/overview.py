"""[상품 관리] 통합 조회. 상품과 기간을 한 번 고르면 관련 결과를 한 화면에 모은다.

노션 'Gold A 설계 정리' 7장의 화면 영역 6개를 그대로 따랐다.
  판매 / 구매 흐름 / 리뷰 / 불만 범주 / 관련 장애 / 데이터 상태
주의 (노션): 지표가 같은 시기에 변한 것은 '조사 단서'일 뿐 원인으로 단정하지 않는다.
        집계 단위가 다른 테이블을 그대로 조인하지 않는다 (금액·건수가 반복됨) -> 영역마다 따로 집계해서 보여준다.
"""

import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("product")
ui.begin_gold_page("trade", "funnels", "reviews")

st.title("통합 조회")
st.caption("같은 시기에 함께 변한 지표는 조사 단서입니다. 원인으로 단정하지 마세요.")

c1, c2 = st.columns([2, 1])
with c1:
    art = ui.pick_products("ov", multi=False)
with c2:
    days = ui.pick_period("ov")

# ---- 판매 (결제일) · 리뷰 (작성일) 요약 카드 ----
# 영역마다 날짜 기준이 달라 같은 줄에 두되 카드 아래 설명에 기준을 적는다.
# 직전 같은 길이 기간(증감 배지)까지 쓰려고 2배 기간을 한 번에 읽는다.
# 결과가 없으면 0건으로 그리지 않고 ui.has_rows 가 사유(완료 실행 없음 등)를 안내한다 (main 의 Gold A 규칙).
all_sales = data.get_product_sales_daily(days * 2)
all_sales = all_sales[all_sales.article_id.isin(art)]
sales = ui.last_days(all_sales, "sales_date_kst", days)
ps = ui.prev_days(all_sales, "sales_date_kst", days)
s_daily = sales.groupby("sales_date_kst")[["sold_quantity", "item_sales_amount"]].sum()

all_rv = data.get_review_product_daily(days * 2)
all_rv = all_rv[all_rv.article_id.isin(art)]
rv = ui.last_days(all_rv, "review_date_kst", days)
prv = ui.prev_days(all_rv, "review_date_kst", days)
cnt, rs, low = rv.review_count.sum(), rv.rating_sum.sum(), rv.low_rating_count.sum()
pcnt, prs = prv.review_count.sum(), prv.rating_sum.sum()
r_daily = rv.groupby("review_date_kst")[["review_count", "rating_sum"]].sum()
note = f"직전 {days}일 대비"

has_sales = ui.has_rows(sales)
has_rv = ui.has_rows(rv)
cards = []
if has_sales:
    cards += [
        {
            "label": "판매 수량",
            "value": f"{int(sales.sold_quantity.sum()):,}",
            "unit": "개",
            "delta": ui.delta(sales.sold_quantity.sum(), ps.sold_quantity.sum()),
            "good": "up",
            "sub": "결제일 기준 · " + note,
            "spark": s_daily.sold_quantity,
        },
        {
            "label": "상품 판매 금액",
            "value": f"{int(sales.item_sales_amount.sum()):,}",
            "unit": "원",
            "delta": ui.delta(sales.item_sales_amount.sum(), ps.item_sales_amount.sum()),
            "good": "up",
            "sub": "결제일 기준 · " + note,
            "spark": s_daily.item_sales_amount,
        },
    ]
if has_rv:
    cards += [
        {
            "label": "리뷰 수",
            "value": f"{int(cnt):,}",
            "unit": "건",
            "delta": ui.delta(cnt, pcnt),
            "good": None,
            "sub": "작성일 기준 · " + note,
            "spark": r_daily.review_count,
        },
        # 기간 평균 별점 = 합계/합계 (일별 평균의 평균이 아님)
        {
            "label": "평균 별점",
            "value": "계산 불가" if cnt == 0 else f"{rs / cnt:.2f}",
            "unit": "/ 5",
            "delta": ui.delta(rs / cnt if cnt else None, prs / pcnt if pcnt else None),
            "good": "up",
            "sub": "낮은 별점(1~2점) " + ui.pct(low / cnt if cnt else float("nan")),
            "spark": data.safe_div(r_daily.rating_sum, r_daily.review_count),
        },
    ]
if cards:
    ui.kpis(cards)
if has_rv:
    st.caption("낮은 별점은 별점 기준이며 AI가 판정한 부정 감성과 다릅니다.")

left, right = st.columns([1.5, 1])
with left, ui.panel("판매 수량", "결제일(KST) 기준 · 개"):
    if has_sales:
        charts.line(
            s_daily[["sold_quantity"]],
            key="ov_sales",
            labels={"sold_quantity": "판매 수량"},
            height="260px",
        )
    else:
        st.caption("판매 결과가 없어 그리지 않습니다.")

# ---- 구매 흐름 (첫 조회일) ----
fn = ui.last_days(data.get_funnel_daily(), "funnel_date_kst", days)
fn = fn[fn.article_id.isin(art)]
with right, ui.panel("구매 흐름", "첫 조회일(KST) 기준 · 방문 수"):
    if ui.has_rows(fn):
        v = fn[["view_sessions", "cart_sessions", "order_sessions", "paid_sessions"]].sum()
        charts.rank(
            [
                ("조회", int(v.view_sessions), charts.color(0)),
                ("담기", int(v.cart_sessions), charts.color(1)),
                ("주문", int(v.order_sessions), charts.color(2)),
                ("결제", int(v.paid_sessions), charts.color(3)),
            ],
            key="ov_funnel",
            max_value=max(int(v.view_sessions), 1),
            fmt=None,
            height="200px",
        )
        # 기간 전환율은 일별 비율의 평균이 아니라 합계끼리 다시 나눈다 (분모 0 이면 계산 불가)
        st.caption(
            f"조회→결제 전환율: {ui.pct(v.paid_sessions / v.view_sessions if v.view_sessions else float('nan'))}"
        )

# ---- 불만 범주 (작성일) ----
st.subheader("불만 범주")
ui.date_note("review")
asp = ui.last_days(data.get_review_aspect_daily(), "review_date_kst", days)
asp = asp[asp.article_id.isin(art)]
if ui.has_rows(asp):
    # 서로 다른 모델 버전을 섞지 않도록 하나를 고른다 (main 의 ui.select_model)
    asp = ui.select_model(asp, "ov_model")
    g = asp.groupby("aspect", as_index=False)[
        ["mentioned_review_count", "negative_review_count"]
    ].sum()
    g["negative_rate"] = data.safe_div(g.negative_review_count, g.mentioned_review_count)
    st.dataframe(g.sort_values("negative_rate", ascending=False), hide_index=True, width="stretch")
    st.caption(
        "속성별 리뷰 수는 합쳐서 전체 리뷰 수로 쓰지 않습니다(리뷰 하나가 여러 속성을 언급). "
        "모델 버전: " + ", ".join(asp.model_version.dropna().unique())
    )

# ---- 관련 장애 (Gold B 기록, 같은 기간) ----
st.subheader("관련 장애")
an = data.get_anomalies().copy()
if "get_anomalies" in data.USING_DUMMY:
    st.info("관련 장애: 실제 조회가 연결되지 않았거나 실패하여 미검증입니다. 미리보기 장애 수치는 표시하지 않습니다.")
else:
    an["detected_at(KST)"] = data.to_kst(an.detected_at)
    st.dataframe(an.drop(columns="detected_at"), hide_index=True, width="stretch")
    st.caption("Gold B의 실제 장애 기록입니다. 같은 기간에 겹친다고 판매 변화의 원인이라고 단정하지 않습니다.")

# ---- 데이터 상태 ----
st.subheader("데이터 상태")
st.caption("선택한 Gold 실행의 실제 공개·보류 상태입니다. 완료 시각을 원천 데이터 처리 완료 범위로 해석하지 마세요.")
st.dataframe(data.get_data_status(), hide_index=True, width="stretch")
st.caption("처리 완료 범위 밖의 낮은 값은 판매 감소가 아니라 데이터 지연일 수 있습니다.")
ui.dummy_note()
