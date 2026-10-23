"""[데이터 관리] 원인 리포트. 데이터: 조사 에이전트가 만든 이상(anomaly)별 원인 리포트.

※ 이 화면은 **임시 구성(제안)** 이다. 노션에는 '에이전트가 원인 리포트를 만들어 대시보드와 슬랙 알림으로
  내보내고 다운로드도 가능하게 한다'는 방향만 있고, 리포트에 넣을 항목은 정해지지 않았다.
  항목은 조사 에이전트 담당과 맞춘 뒤 data.get_rca_reports() 와 이 화면을 함께 고친다.

핵심 원칙 (노션): 같은 시기에 변한 지표는 조사 단서일 뿐 원인으로 단정하지 않는다
  -> 화면에서 '확인된 사실'과 '추정'을 나눠서 보여준다.
이 화면은 읽기 전용이다 (재처리 승인 버튼은 승인 화면 담당 영역, Airflow 결정 이후 설계).
리포트에는 리뷰 원문·개인정보를 담지 않는다.
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("원인 리포트")
st.info("임시 구성입니다. 리포트 항목은 조사 에이전트 담당과 맞춘 뒤 확정합니다.")

df = data.get_rca_reports().copy()
df["detected_at_kst"] = data.to_kst(df.detected_at)
df = df.sort_values("detected_at_kst", ascending=False)

pick = st.selectbox(
    "이상 선택",
    df.anomaly_id,
    format_func=lambda i: (
        f"{i} · {df.set_index('anomaly_id').loc[i, 'scenario']} · "
        f"{df.set_index('anomaly_id').loc[i, 'target']}"
    ),
)
r = df.set_index("anomaly_id").loc[pick]

# 조치 진행 단계: 이상 -> 승인 -> 재처리 -> 재판정 -> 검증 (reprocess_events 의 step 과 대응)
STEPS = ["승인 대기", "승인", "재처리", "재판정", "검증"]
c = st.columns(4)
c[0].metric("규칙", r.rule)
c[1].metric("시나리오", r.scenario)
c[2].metric("대상", r.target)
c[3].metric("탐지(KST)", r.detected_at_kst.strftime("%m-%d %H:%M"))

st.subheader("원인 요약")
st.write(r.summary)

left, right = st.columns(2)
with left:
    st.subheader("확인된 사실")
    for f in r.facts:
        st.markdown(f"- {f}")
with right:
    st.subheader("추정 (미확인)")
    for a in r.assumptions:
        st.markdown(f"- {a}")

st.subheader("영향 범위")
st.write(r.impact)

st.subheader("근거")
st.dataframe(r.evidence, hide_index=True, width="stretch")

st.subheader("조치 진행")
idx = STEPS.index(r.action_step) if r.action_step in STEPS else 0
st.progress(
    (idx + 1) / len(STEPS),
    text=" → ".join(f"**{s}**" if i == idx else s for i, s in enumerate(STEPS)),
)
st.caption("승인·재처리 이력은 '재처리 이력' 화면에서 확인합니다. 원인을 고친 뒤에 승인합니다.")

# 다운로드: 같은 내용을 마크다운 파일로 (리뷰 원문·개인정보는 포함하지 않음)
md = "\n".join(
    [
        f"# 원인 리포트 {pick}",
        f"- 규칙: {r.rule} / 시나리오: {r.scenario} / 대상: {r.target}",
        f"- 탐지(KST): {r.detected_at_kst:%Y-%m-%d %H:%M}",
        "",
        "## 원인 요약",
        r.summary,
        "",
        "## 확인된 사실",
        *[f"- {f}" for f in r.facts],
        "",
        "## 추정 (미확인)",
        *[f"- {a}" for a in r.assumptions],
        "",
        "## 영향 범위",
        r.impact,
        "",
        "## 근거",
        *[f"- {e['table']}: {e['finding']}" for e in r.evidence],
        "",
        f"## 조치 진행: {r.action_step}",
    ]
)
st.download_button("리포트 다운로드 (.md)", md, file_name=f"rca-{pick}.md", mime="text/markdown")
st.caption("※ 현재는 더미 데이터입니다.")
