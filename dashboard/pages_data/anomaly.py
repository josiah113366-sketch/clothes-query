"""[데이터 관리] 이상탐지. 데이터: gold_b.anomaly_current (탐지 담당이 정의한 표, 2026-10-25 실데이터 연결).

역할 구분 (노션): 한 건만 보고 아는 것은 Gold B 원장이, 여러 건을 모아 평소와 비교해야 아는 것은 탐지가 한다.
규칙: R1 PG 장애, R3 Bronze 적재 지연, R4 형식 오류, R5 성공 결제 중복, R6 총액 불일치.
이상이 없는 것(빈 표)은 비정상이 아니라 정상 상태다.
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("이상탐지")

df = data.get_anomalies().copy()

if df.empty:
    st.success("현재 열린 이상이 없습니다.")
else:
    df["detected_at_kst"] = data.to_kst(df.detected_at)
    df["규칙"] = df.rule_id.map(lambda r: data.RULE_LABELS.get(r, r))

    c1, c2 = st.columns(2)
    rules = c1.multiselect("규칙", sorted(df["규칙"].unique()), default=sorted(df["규칙"].unique()))
    sts = c2.multiselect("상태", sorted(df.status.unique()), default=sorted(df.status.unique()))
    show = (
        df[df["규칙"].isin(rules) & df.status.isin(sts)]
        .sort_values("detected_at_kst", ascending=False)[
            ["anomaly_id", "규칙", "scope_key", "observed_value", "baseline_value", "status", "detected_at_kst"]
        ]
        .rename(
            columns={
                "anomaly_id": "이상 id",
                "scope_key": "대상",
                "observed_value": "관측값",
                "baseline_value": "기준값",
                "status": "상태",
                "detected_at_kst": "감지(KST)",
            }
        )
    )
    st.dataframe(show, hide_index=True, width="stretch")

st.caption(
    "이상이 잡히면 조사 에이전트가 원인 리포트를 쓰고, 원인을 고친 뒤 승인 -> 재처리 순서로 진행합니다 (재처리 이력 화면)."
)
if "get_anomalies" in data.USING_DUMMY:
    st.caption("※ 현재는 더미 데이터입니다.")
