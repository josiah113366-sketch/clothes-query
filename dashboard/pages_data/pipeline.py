"""[데이터 관리] 파이프라인 상태. 데이터: Gold B bronze_lag_snapshots(+ 신뢰성 점검).

시나리오 2(트래픽 폭주): 파이프라인이 제때 처리하지 못하고 밀리는가?
읽는 법 (노션): S3 Sink 는 15분마다 파일을 쓰므로 lag_sec 은 정상일 때도 0 ~ 약 900초를 톱니 모양으로 반복한다.
        이 모양이 '평소'다. 톱니 꼭대기가 계속 높아지거나 connector_state 가 RUNNING 이 아니면 이상.
        유입(topic_messages)은 그대로인데 지연만 커졌다면 폭주가 아니라 Bronze 적재 자체의 문제다.
시각은 UTC 로 저장되어 있어 화면에서는 KST 로 바꿔 보여준다.
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("파이프라인 상태")

lag = data.get_bronze_lag(180).copy()
lag["collected_at_kst"] = data.to_kst(lag.collected_at)

# 지연 톱니의 '평소' 상한(초). 15분 파일 주기 + 여유. 운영하면서 조정한다.
NORMAL_MAX_SEC = 900 + 120

latest = lag[lag.collected_at == lag.collected_at.max()]
bad = latest[(latest.connector_state != "RUNNING") | (latest.lag_sec > NORMAL_MAX_SEC)]
c1, c2 = st.columns(2)
c1.metric("지연/이상 토픽", len(bad))
c2.metric("마지막 측정(KST)", latest.collected_at_kst.max().strftime("%H:%M"))
if len(bad):
    st.warning("평소 범위를 넘었거나 커넥터가 RUNNING 이 아닌 토픽이 있습니다.")
    st.dataframe(
        bad[["topic", "lag_sec", "lag_msgs", "connector_state"]], hide_index=True, width="stretch"
    )

st.subheader("토픽별 Bronze 적재 지연(초)")
pv = lag.pivot(index="collected_at_kst", columns="topic", values="lag_sec")
st.line_chart(pv)
st.caption(f"평소 모양: 0~약 900초 톱니. 위 경고 기준은 {NORMAL_MAX_SEC}초(코드 NORMAL_MAX_SEC).")

st.subheader("원장 신뢰성 점검")
st.dataframe(
    data.get_reliability_checks().assign(checked_at=lambda d: data.to_kst(d.checked_at)),
    hide_index=True,
    width="stretch",
)
st.caption(
    "점검에 문제가 나오면 그 시간대의 탐지 결과는 믿지 않고 Gold B부터 고친 뒤 재판정합니다."
)
st.caption("※ 현재는 더미 데이터입니다.")
