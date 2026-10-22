"""[데이터 관리] 결제 관제. 데이터: Gold B payment_attempts 뷰 (결제 시도 1건 = 1줄).

시나리오 1(PG 장애): 특정 PG 에 장애가 생겨 결제가 실패하는가?
읽는 법 (노션):
  - 실패 원인은 뷰가 분류한다: PG(PG_TIMEOUT, PG_ERROR) / CUSTOMER(잔액부족·한도초과·거절) / UNKNOWN(그 외).
    실패 = PG + CUSTOMER + UNKNOWN 이 항상 성립한다.
  - 고객 원인 실패는 장애가 아니다. 'PG 원인 실패 비율'을 PG 별로 본다.
  - 같은 payment_id 중복은 뷰에서 이미 합쳐져 있다 (copies 컬럼으로 도착 횟수 확인).
  - 이상 판정(묶어 세기)은 탐지 담당의 일이다. 이 화면은 원장을 읽기 쉽게 보여주는 용도다.
"""

import pandas as pd
import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("결제 관제")
hours = st.slider("조회 기간(최근 N시간)", 1, 6, 3)

df = data.get_payment_attempts(6).copy()
df["completed_at_kst"] = data.to_kst(df.completed_at)
df = df[df.completed_at > df.completed_at.max() - pd.Timedelta(hours=hours)]

fail = df[df.status == "FAILED"]
m = st.columns(4)
m[0].metric("결제 시도", f"{len(df):,}")
m[1].metric("실패", f"{len(fail):,}")
m[2].metric("PG 원인 실패", f"{int((fail.failure_cause == 'PG').sum()):,}")
m[3].metric("고객 원인 실패", f"{int((fail.failure_cause == 'CUSTOMER').sum()):,}")

st.subheader("PG별 PG 원인 실패 비율 (10분 단위)")
pgf = df.assign(bucket=df.completed_at_kst.dt.floor("10min"), pg_fail=(df.failure_cause == "PG"))
rate = pgf.groupby(["bucket", "pg"]).pg_fail.mean().unstack("pg")
st.line_chart(rate)
st.caption("고객 원인 실패는 제외하고 PG 원인 실패만 비율로 봅니다.")

st.subheader("실패 원인별 건수")
st.bar_chart(fail.groupby(["pg", "failure_cause"]).size().unstack("failure_cause").fillna(0))

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
                "copies",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
st.caption("※ 현재는 더미 데이터입니다.")
