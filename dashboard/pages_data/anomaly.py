"""[데이터 관리] 이상탐지. 데이터: gold_b.anomaly (탐지 담당이 정의하는 표).

역할 구분 (노션): 한 건만 보고 아는 것은 Gold B 원장이, 여러 건을 모아 평소와 비교해야 아는 것은 탐지가 한다.
이 화면은 탐지 결과를 보여주기만 한다. 컬럼은 아직 임시이며, 탐지 담당이 표를 확정하면
data.get_anomalies() 만 맞추면 된다. 시나리오: PG 장애 / 트래픽 폭주 / 스키마 오염.
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("이상탐지")

df = data.get_anomalies().copy()
df["detected_at_kst"] = data.to_kst(df.detected_at)
df = df.drop(columns="detected_at")

c1, c2 = st.columns(2)
sc = c1.multiselect("시나리오", sorted(df.scenario.unique()), default=sorted(df.scenario.unique()))
lv = c2.multiselect("심각도", sorted(df.severity.unique()), default=sorted(df.severity.unique()))
st.dataframe(
    df[df.scenario.isin(sc) & df.severity.isin(lv)].sort_values("detected_at_kst", ascending=False),
    hide_index=True,
    width="stretch",
)
st.caption(
    "이상이 잡히면 조사 에이전트가 원인 리포트를 쓰고, 원인을 고친 뒤 승인 -> 재처리 순서로 진행합니다 (재처리 이력 화면)."
)
st.caption("※ 현재는 더미 데이터입니다. 컬럼은 임시입니다.")
