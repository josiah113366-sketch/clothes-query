"""[데이터 관리] 형식 오류. 데이터: Gold B malformed_events, malformed_messages 뷰.

시나리오 3(스키마 오염): 데이터 형식이 깨졌는가? 어디서, 언제부터인가?
읽는 법 (노션):
  - 오류 사유 4가지: PARSE_ERROR / MISSING_FIELD / TYPE_MISMATCH / INVALID_VALUE.
  - malformed_events 는 '오류 하나 = 한 줄'이라 COUNT(*) 로 세면 깨진 메시지 수가 부풀어 보인다.
    깨진 메시지 수는 위치(토픽, 파티션, offset)로 합친 malformed_messages 기준으로 센다.
  - 규칙이 바뀌면 rule_version 별로 쌓이므로 '현재 버전'만 센다.
  - 오염이 시작된 시점 = 가장 이른 kafka_timestamp (재처리 범위의 시작점이 된다).
  - raw_sample(원문 일부)은 이 대시보드에 올리지 않는다 (조회 권한 제한 대상).
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("형식 오류")

ev = data.get_malformed_events().copy()
# 규칙 버전: 현재 버전만 센다. 더미에서는 하나뿐이라 선택지가 하나다.
ver = st.selectbox("규칙 버전(현재 버전만 집계)", sorted(ev.rule_version.unique()))
ev = ev[ev.rule_version == ver]
msg = data.to_malformed_messages(ev)

m = st.columns(3)
m[0].metric("깨진 메시지 수", f"{len(msg):,}")
m[1].metric("오류(필드) 건수", f"{len(ev):,}")
m[2].metric("오염 시작(KST)", data.to_kst(ev.kafka_timestamp).min().strftime("%m-%d %H:%M"))
st.caption(
    "깨진 메시지 수는 위치 기준(malformed_messages), 오류 건수는 필드 기준(malformed_events)이라 값이 다릅니다."
)

ev["kafka_timestamp_kst"] = data.to_kst(ev.kafka_timestamp)
st.subheader("토픽별 깨진 메시지 (10분 단위)")
msg["bucket"] = data.to_kst(msg.kafka_timestamp).dt.floor("10min")
st.bar_chart(msg.groupby(["bucket", "topic"]).size().unstack("topic").fillna(0))

st.subheader("사유별 오류 건수")
st.bar_chart(ev.groupby(["field", "reason"]).size().unstack("reason").fillna(0))

with st.expander("깨진 메시지 목록 (위치 기준)"):
    st.dataframe(msg, hide_index=True, width="stretch")
st.caption("※ 현재는 더미 데이터입니다.")
