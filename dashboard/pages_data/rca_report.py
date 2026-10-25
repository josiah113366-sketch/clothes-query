"""[데이터 관리] 원인 리포트. 데이터: agent.investigation_reports + gold_b.anomaly_current (2026-10-25 실데이터 연결).

핵심 원칙 (노션): 같은 시기에 변한 지표는 조사 단서일 뿐 원인으로 단정하지 않는다
  -> 화면에서 '확인된 사실(FACT)'과 '추정(ASSUMPTION)'을 나눠서 보여준다.
이 화면은 읽기 전용이다 (재처리 승인 버튼은 승인 화면 담당 영역).
리포트에는 리뷰 원문·개인정보를 담지 않는다.
"""

import streamlit as st

import data
from auth import require_role

require_role("data")

st.title("원인 리포트")

LAYER_LABELS = {"PAYMENT": "결제", "INGEST": "적재", "DATA_QUALITY": "데이터 품질", "UNKNOWN": "미확인"}

df = data.get_rca_reports().copy()

if df.empty:
    st.info("아직 조사 리포트가 없습니다.")
else:
    df["created_at_kst"] = data.to_kst(df.created_at)
    df["anomaly_detected_at_kst"] = data.to_kst(df.anomaly_detected_at)
    df = df.sort_values("created_at_kst", ascending=False)

    pick = st.selectbox(
        "리포트 선택",
        df.report_id,
        format_func=lambda i: (
            f"{i} · {data.RULE_LABELS.get(df.set_index('report_id').loc[i, 'rule_id'], df.set_index('report_id').loc[i, 'rule_id'])} · "
            f"{df.set_index('report_id').loc[i, 'scope_key']}"
        ),
    )
    r = df.set_index("report_id").loc[pick]

    c = st.columns(4)
    c[0].metric("규칙", data.RULE_LABELS.get(r.rule_id, r.rule_id))
    c[1].metric("대상", r.scope_key)
    c[2].metric("원인 층", LAYER_LABELS.get(r.cause_layer, r.cause_layer))
    c[3].metric("조사(KST)", r.created_at_kst.strftime("%m-%d %H:%M"))

    if r.problems:
        st.warning("검증 미통과: " + " / ".join(r.problems))

    st.subheader("결론")
    st.write(r.conclusion)

    facts = [c["text"] for c in r.claims if c.get("kind") == "FACT"]
    assumptions = [c["text"] for c in r.claims if c.get("kind") == "ASSUMPTION"]
    left, right = st.columns(2)
    with left:
        st.subheader("확인된 사실")
        for f in facts:
            st.markdown(f"- {f}")
        if not facts:
            st.caption("없음")
    with right:
        st.subheader("추정 (미확인)")
        for a in assumptions:
            st.markdown(f"- {a}")
        if not assumptions:
            st.caption("없음")

    st.caption(f"이상 감지(KST): {r.anomaly_detected_at_kst:%Y-%m-%d %H:%M} · 모델: {r.model_id}")
    st.caption("승인·재처리 이력은 '재처리 이력' 화면에서 확인합니다. 원인을 고친 뒤에 승인합니다.")

    # 다운로드: 같은 내용을 마크다운 파일로 (리뷰 원문·개인정보는 포함하지 않음)
    md = "\n".join(
        [
            f"# 원인 리포트 {pick}",
            f"- 규칙: {data.RULE_LABELS.get(r.rule_id, r.rule_id)} / 대상: {r.scope_key}",
            f"- 조사(KST): {r.created_at_kst:%Y-%m-%d %H:%M} / 모델: {r.model_id}",
            "",
            "## 결론",
            r.conclusion,
            "",
            "## 확인된 사실",
            *[f"- {f}" for f in facts],
            "",
            "## 추정 (미확인)",
            *[f"- {a}" for a in assumptions],
        ]
    )
    st.download_button("리포트 다운로드 (.md)", md, file_name=f"rca-{pick}.md", mime="text/markdown")

if "get_rca_reports" in data.USING_DUMMY:
    st.caption("※ 현재는 더미 데이터입니다.")
