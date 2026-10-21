"""[데이터 관리] 재처리 이력. 데이터: Gold B reprocess_events (줄을 고치지 않고 새 줄만 쌓는 기록).

읽는 법 (노션):
  - 현재 상태 = 요청(request_id)별 '마지막 줄'의 step.
  - 흐름: REQUESTED -> APPROVED/REJECTED -> STARTED -> LEDGER_REPLACED(1시간 폴더마다 한 줄) -> REDETECTED -> VERIFIED
    중간 실패는 FAILED (detail 에 이유). 원본이 없는 구간은 재시도 없이 바로 FAILED.
  - 교체 단위는 이벤트 시각 기준 1시간 폴더다. 승인 범위가 15:10~15:30 이어도 15시대 폴더 전체를 다시 채운다.
  - 반드시 원인(규칙·코드)을 고친 뒤 승인한다. 이 화면은 읽기 전용이며 승인 버튼은 두지 않았다
    (승인 화면은 별도 담당 영역).
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("재처리 이력")

ev = data.get_reprocess_events().copy()
for col in ("at", "window_start", "window_end"):
    ev[col] = data.to_kst(ev[col])
ev = ev.sort_values(["request_id", "at"])

st.subheader("요청별 현재 상태")
cur = ev.groupby("request_id", as_index=False).last()[
    ["request_id", "step", "at", "rule_version", "source", "window_start", "window_end"]
]
st.dataframe(cur, hide_index=True, width="stretch")

st.subheader("단계 이력")
rid = st.selectbox("요청", sorted(ev.request_id.unique()))
st.dataframe(
    ev[ev.request_id == rid][
        ["at", "step", "actor", "window_start", "window_end", "rule_version", "source"]
    ],
    hide_index=True,
    width="stretch",
)
st.caption("※ 현재는 더미 데이터입니다. 시각은 KST로 변환해 보여줍니다.")
