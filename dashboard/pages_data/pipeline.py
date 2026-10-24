"""[데이터 관리] 파이프라인 상태. 데이터: Gold B bronze_lag_snapshots(+ 신뢰성 점검).

시나리오 2(트래픽 폭주): 파이프라인이 제때 처리하지 못하고 밀리는가?
읽는 법 (노션): S3 Sink 는 15분마다 파일을 쓰므로 lag_sec 은 정상일 때도 0 ~ 약 900초를 톱니 모양으로 반복한다.
        이 모양이 '평소'다. 톱니 꼭대기가 계속 높아지거나 connector_state 가 RUNNING 이 아니면 이상.
        유입(topic_messages)은 그대로인데 지연만 커졌다면 폭주가 아니라 Bronze 적재 자체의 문제다.
시각은 UTC 로 저장되어 있어 화면에서는 KST 로 바꿔 보여준다.
"""

import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("data")

st.title("파이프라인 상태")

lag = data.get_bronze_lag(180).copy()
lag["collected_at_kst"] = data.to_kst(lag.collected_at)

# 지연 톱니의 '평소' 상한(초). 15분 파일 주기 + 여유. 운영하면서 조정한다.
NORMAL_MAX_SEC = 900 + 120

latest = lag[lag.collected_at == lag.collected_at.max()]
bad = latest[(latest.connector_state != "RUNNING") | (latest.lag_sec > NORMAL_MAX_SEC)]
per_min = lag.groupby("collected_at_kst")[["lag_sec", "lag_msgs"]].max()
ui.kpis(
    [
        {
            "label": "지연/이상 토픽",
            "value": f"{len(bad)}",
            "unit": f"/ {latest.topic.nunique()}개",
            "color": charts.BAD if len(bad) else charts.GOOD,
            "sub": "평소 범위 초과 또는 RUNNING 아님",
        },
        {
            "label": "최대 지연",
            "value": f"{latest.lag_sec.max():,.0f}",
            "unit": "초",
            "sub": "마지막 측정, 토픽 중 최대",
            "spark": per_min.lag_sec,
        },
        {
            "label": "밀린 메시지",
            "value": f"{int(latest.lag_msgs.sum()):,}",
            "unit": "건",
            "sub": "마지막 측정, 토픽 합계",
            "spark": per_min.lag_msgs,
        },
        {
            "label": "마지막 측정(KST)",
            "value": latest.collected_at_kst.max().strftime("%H:%M"),
            "sub": "1분마다 측정",
        },
    ]
)
if len(bad):
    st.warning("평소 범위를 넘었거나 커넥터가 RUNNING 이 아닌 토픽이 있습니다.")
    st.dataframe(
        bad[["topic", "lag_sec", "lag_msgs", "connector_state"]], hide_index=True, width="stretch"
    )

with ui.panel("토픽별 Bronze 적재 지연", "1분 측정 · KST · 초"):
    pv = lag.pivot(index="collected_at_kst", columns="topic", values="lag_sec")
    pv = pv[sorted(pv.columns)]  # 토픽 이름 순서 = 색 순서 (고정)
    charts.line(
        pv,
        key="pl_lag",
        fmt="sec",
        area=False,
        threshold=NORMAL_MAX_SEC,
        threshold_label="경고 기준",
        height="340px",
    )
    st.caption(
        f"평소 모양: 0~약 900초 톱니. 점선 경고 기준은 {NORMAL_MAX_SEC}초(코드 NORMAL_MAX_SEC)."
    )

with ui.panel("원장 신뢰성 점검"):
    st.dataframe(
        data.get_reliability_checks().assign(checked_at=lambda d: data.to_kst(d.checked_at)),
        hide_index=True,
        width="stretch",
    )
st.caption(
    "점검에 문제가 나오면 그 시간대의 탐지 결과는 믿지 않고 Gold B부터 고친 뒤 재판정합니다."
)
st.caption("※ 현재는 더미 데이터입니다.")
