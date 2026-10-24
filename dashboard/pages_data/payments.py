"""[데이터 관리] 결제 관제. 데이터: Gold B payment_attempts 뷰 (결제 시도 1건 = 1줄).

시나리오 1(PG 장애): 특정 PG 에 장애가 생겨 결제가 실패하는가?
읽는 법 (노션):
  - 실패 원인은 뷰가 분류한다: PG(PG_TIMEOUT, PG_ERROR) / CUSTOMER(잔액부족·한도초과·거절) / UNKNOWN(그 외).
    실패 = PG + CUSTOMER + UNKNOWN 이 항상 성립한다.
  - 고객 원인 실패는 장애가 아니다. 'PG 원인 실패 비율'을 PG 별로 본다.
  - 같은 결제가 여러 번 들어와도 뷰가 Kafka 위치 순서로 마지막 이벤트 하나만 보여 준다.
    여러 파티션에 나뉘었거나 순서가 이상하거나 마지막이 형식 오류인 결제는 보류되어 빠진다 (payment_conflicts 뷰).
  - 이상 판정(묶어 세기)은 탐지 담당의 일이다. 이 화면은 원장을 읽기 쉽게 보여주는 용도다.
"""

import pandas as pd
import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("data")

st.title("결제 관제")
hours = st.slider("조회 기간(최근 N시간)", 1, 6, 3)

df = data.get_payment_attempts(6).copy()
df["completed_at_kst"] = data.to_kst(df.completed_at)
df = df[df.completed_at > df.completed_at.max() - pd.Timedelta(hours=hours)]

fail = df[df.status == "FAILED"]
pgf = df.assign(
    bucket=df.completed_at_kst.dt.floor("10min"),
    pg_fail=(df.failure_cause == "PG"),
    failed=(df.status == "FAILED"),
)
by10 = pgf.groupby("bucket")[["pg_fail", "failed"]].agg(["sum", "count"])
ui.kpis(
    [
        {
            "label": "결제 시도",
            "value": f"{len(df):,}",
            "unit": "건",
            "sub": f"최근 {hours}시간",
            "spark": by10[("failed", "count")],
        },
        {
            "label": "실패",
            "value": f"{len(fail):,}",
            "unit": "건",
            "sub": "실패율 " + ui.pct(len(fail) / len(df) if len(df) else float("nan")),
            "spark": by10[("failed", "sum")],
        },
        {
            "label": "PG 원인 실패",
            "value": f"{int((fail.failure_cause == 'PG').sum()):,}",
            "unit": "건",
            "sub": "PG_TIMEOUT · PG_ERROR",
            "spark": by10[("pg_fail", "sum")],
        },
        {
            "label": "고객 원인 실패",
            "value": f"{int((fail.failure_cause == 'CUSTOMER').sum()):,}",
            "unit": "건",
            "sub": "장애 아님 (잔액·한도·거절)",
        },
    ]
)

left, right = st.columns([1.6, 1])
with left, ui.panel("PG별 PG 원인 실패 비율", "10분 단위 · KST"):
    rate = pgf.groupby(["bucket", "pg"]).pg_fail.mean().unstack("pg")
    # PG 색은 PG 이름 순서로 고정 (조회 기간을 바꿔도 같은 PG 는 같은 색)
    pgs = sorted(df.pg.unique())
    charts.line(
        rate[[p for p in pgs if p in rate.columns]],
        key="pay_rate",
        fmt="pct",
        colors=[charts.color(pgs.index(p)) for p in pgs if p in rate.columns],
    )
    st.caption("고객 원인 실패는 제외하고 PG 원인 실패만 비율로 봅니다.")
with right:
    by_pg = pgf.groupby("pg").pg_fail.mean()
    worst = float(by_pg.max()) if len(by_pg) else None
    # 상태 색 기준(임시): 5% 미만 정상, 15% 미만 주의, 그 이상 위험.
    # 탐지 규칙의 기준이 아니라 화면 색 구분용이다.
    tone = (
        charts.GOOD
        if worst is None or worst < 0.05
        else charts.WARN
        if worst < 0.15
        else charts.BAD
    )
    with ui.panel("가장 높은 PG 원인 실패 비율", f"최근 {hours}시간"):
        charts.gauge(worst, key="pay_gauge", label=by_pg.idxmax() if len(by_pg) else "", tone=tone)
    with ui.panel("PG별 PG 원인 실패 비율", f"최근 {hours}시간 · 시도 수"):
        cnt = pgf.groupby("pg").size()
        charts.rank(
            [
                (f"{p} ({int(cnt[p]):,}건)", float(by_pg[p]), charts.color(pgs.index(p)))
                for p in pgs
            ],
            key="pay_rank",
            max_value=max(worst or 0, 0.01),
        )

with ui.panel("실패 원인별 건수", "PG별 · 원인 쌓기"):
    charts.bar(
        fail.groupby(["pg", "failure_cause"]).size().unstack("failure_cause").fillna(0),
        key="pay_cause",
        stacked=True,
        height="260px",
    )

with st.expander("실패 결제 목록"):
    st.dataframe(
        fail[
            [
                "payment_id",
                "order_id",
                "attempt_no",
                "pg",
                "failure_code",
                "failure_cause",
                "completed_at_kst",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
if "get_payment_attempts" in data.USING_DUMMY:
    st.caption("※ 현재는 더미 데이터입니다.")
