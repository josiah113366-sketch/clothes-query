"""[데이터 관리] 재처리 승인. 이상을 보고, 조사 리포트를 읽고, 사람이 승인하거나 거절한다.

흐름 (설계: docs/design/agent/approval-flow.md)
  이상 -> [요청] REQUESTED -> [승인] APPROVED (또는 [거절] REJECTED) -> 재처리 시작 -> 재판정 -> VERIFIED
이 화면은 요청·승인·거절 버튼만 둔다. 규칙(승인자 확인, 상태 확인, 중복 승인 방지, 재시도 횟수 계산)은
agent/approval/approval.py가 지키고, 이 화면은 그 함수를 부르고 거절 이유를 보여줄 뿐이다.

반드시 원인(규칙·코드·원본)을 고친 뒤에 승인한다. 승인자는 로그인한 사용자 이메일이어야 한다 (공용 계정·dev 로그인은 거절).
환경변수가 없으면 연습 모드(가짜 저장소)로 열린다. 연결 방법은 approval_io.py 맨 위에 있다.
"""
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import approval_io as io
from auth import current_user, require_role

require_role("data")

st.title("재처리 승인")


@st.cache_resource
def backend():
    return io.make_backend()


b = backend()
now = datetime.utcnow().replace(microsecond=0)     # 승인 규칙 코드는 UTC 시각을 쓴다


def kst(value) -> str:
    return (io.ap._parse(value) + timedelta(hours=9)).strftime("%m-%d %H:%M")


@st.cache_data(ttl=15)
def _candidates(_b, key):
    return io.load_candidates(_b, datetime.utcnow().replace(microsecond=0))


@st.cache_data(ttl=15)
def _requests(_b, key):
    return io.load_requests(_b, datetime.utcnow().replace(microsecond=0))


@st.cache_data(ttl=60)
def _report(_b, anomaly_id):
    return io.load_report(_b, anomaly_id)


def clear_caches():
    _candidates.clear()
    _requests.clear()


def refresh():
    clear_caches()
    st.rerun()


# ---- 승인자 확인 -----------------------------------------------------------
user, _ = current_user()
actor = io.PRACTICE_ACTOR if b.mode == "PRACTICE" else user
actor_ok = True
try:
    io.ap.check_actor(actor)
except io.ApprovalError as error:
    actor_ok = False
    actor_error = error.message

if b.mode == "PRACTICE":
    st.warning("연습 모드입니다. 가짜 저장소와 가짜 Airflow로 화면만 확인합니다. 실제 재처리는 시작되지 않습니다.")
st.caption(f"승인자: {actor}")
if not actor_ok:
    st.error(f"승인·요청·거절을 할 수 없습니다. {actor_error}")

flash = st.session_state.pop("flash", None)
if flash:
    (st.success if flash[0] == "ok" else st.error)(flash[1])

WARNING_TEXT = {
    "UNFIXABLE_BY_REPROCESS": "이 규칙(R5·R6)은 원본이 그대로면 재처리해도 해소되지 않을 수 있습니다. 원본을 먼저 고쳤는지 확인하세요.",
    "OUTSIDE_KAFKA_RETENTION": "Kafka 보관 기간(3일)을 넘긴 구간이라 Kafka로 다시 만들 수 없을 수 있습니다.",
}
STATE_TEXT = {"REQUESTED": "승인 대기", "APPROVED": "승인됨", "REJECTED": "거절됨", "STARTED": "재처리 중", "LEDGER_REPLACED": "교체 완료",
              "REDETECTED": "재판정 완료", "VERIFIED": "검증 완료", "FAILED": "실패", "EXPIRED_REQUEST": "요청 만료", "EXPIRED_APPROVAL": "승인 만료"}

# ---- 1. 승인 대기 -----------------------------------------------------------
requests = _requests(b, b.mode)
waiting = [r for r in requests if r["state"] == "REQUESTED"]
st.header("승인 대기")
if not waiting:
    st.info("승인을 기다리는 요청이 없습니다. 아래 '재처리 요청'에서 이상을 골라 요청을 만들 수 있습니다.")
else:
    pick = st.selectbox("요청 선택", [r["request_id"] for r in waiting],
                        format_func=lambda i: next(f"{kst(r['requested_at'])} · {r['rule_id']} · {i}" for r in waiting if r["request_id"] == i))
    req = next(r for r in waiting if r["request_id"] == pick)
    c = st.columns(4)
    c[0].metric("규칙", str(req["rule_id"]))
    c[1].metric("재처리 범위(KST)", f"{kst(req['window_start'])} ~ {kst(req['window_end'])}")
    c[2].metric("읽는 곳", str(req["source"]))
    c[3].metric("시도 번호", str(req["attempt"]))
    for w in req["warnings"]:
        st.warning(WARNING_TEXT[w])
    report = _report(b, req["anomaly_id"]) if req["anomaly_id"] else None
    if report:
        st.subheader("조사 리포트")
        if report["problems"]:
            st.error("검증을 통과하지 못한 리포트입니다. 결론을 그대로 믿지 마세요.")
        st.write(f"**원인 층:** {report['cause_layer']}")
        st.write(report["conclusion"])
        left, right = st.columns(2)
        facts = [x for x in report["claims"] if x.get("kind") == "FACT"]
        guesses = [x for x in report["claims"] if x.get("kind") != "FACT"]
        left.markdown("**확인된 사실**")
        for x in facts:
            left.markdown(f"- {x.get('text')}")
        right.markdown("**추정 (미확인)**")
        for x in guesses:
            right.markdown(f"- {x.get('text')}")
        for p in report["problems"]:
            st.caption(f"검증 문제: {p}")
    else:
        st.info("이 이상의 조사 리포트가 아직 없습니다.")
    fixed = st.checkbox("원인(규칙·코드·원본)을 고쳤음을 확인했습니다", key=f"fixed-{pick}")
    reason = st.text_input("거절 이유 (거절할 때만)", key=f"reason-{pick}")
    a, r = st.columns(2)
    if a.button("승인", type="primary", disabled=not (fixed and actor_ok), key=f"approve-{pick}"):
        try:
            res = io.ap.approve(pick, actor, datetime.utcnow().replace(microsecond=0), b.query, b.write, b.trigger, b.cfg)
            note = {"TRIGGERED": "재처리 DAG를 시작했습니다.", "ALREADY_TRIGGERED": "이미 시작된 요청입니다.",
                    "POLLER": "승인했습니다. 재처리 DAG가 5분 안에 읽어서 시작합니다."}.get(res["airflow"], res["airflow"])
            st.session_state["flash"] = ("ok", f"승인했습니다 ({pick}). {note}")
        except io.ApprovalError as error:
            st.session_state["flash"] = ("err", error.message)
        refresh()
    if r.button("거절", disabled=not actor_ok, key=f"reject-{pick}"):
        try:
            io.ap.reject(pick, actor, reason, datetime.utcnow().replace(microsecond=0), b.query, b.write, b.cfg)
            st.session_state["flash"] = ("ok", f"거절했습니다 ({pick}).")
        except io.ApprovalError as error:
            st.session_state["flash"] = ("err", error.message)
        refresh()
    if not fixed:
        st.caption("원인을 고쳤는지 확인하는 칸을 체크해야 승인할 수 있습니다.")

# ---- 2. 재처리 요청 ---------------------------------------------------------
st.header("재처리 요청")
cands = _candidates(b, b.mode)
if not cands:
    st.info("최근 48시간에 요청할 수 있는 이상이 없습니다.")
else:
    pick_a = st.selectbox("이상 선택", [x["anomaly_id"] for x in cands],
                          format_func=lambda i: next(f"{kst(x['detected_at'])} · {x['rule_id']} · {x['scope_key']} · {x['status']}" for x in cands if x["anomaly_id"] == i))
    an = next(x for x in cands if x["anomaly_id"] == pick_a)
    st.write(f"범위(KST): {kst(an['window_start'])} ~ {kst(an['window_end'])} · 지표 {an['metric']} = {an['observed_value']} (기준 {an['baseline_value']})")
    rep = _report(b, pick_a)
    if not an["reprocessable"]:
        st.info(f"{an['rule_id']}는 재처리가 값을 바꾸지 않는 규칙이라 재처리 대상이 아닙니다.")
    if st.button("재처리 요청", disabled=not (actor_ok and an["reprocessable"]), key=f"request-{pick_a}"):
        try:
            res = io.ap.request_reprocess(an, rep["report_id"] if rep else None, actor, datetime.utcnow().replace(microsecond=0), b.query, b.write, b.cfg)
            extra = " ".join(WARNING_TEXT[w] for w in res["warnings"])
            st.session_state["flash"] = ("ok", f"요청했습니다 ({res['request_id']}). 위 '승인 대기'에서 승인하세요. {extra}")
        except io.ApprovalError as error:
            st.session_state["flash"] = ("err", error.message)
        refresh()

# ---- 3. 최근 요청 현황 --------------------------------------------------------
st.header("최근 24시간 요청 현황")
if requests:
    table = pd.DataFrame([{"요청": r["request_id"], "상태": STATE_TEXT.get(r["state"], r["state"]), "규칙": r["rule_id"],
                           "범위(KST)": f"{kst(r['window_start'])} ~ {kst(r['window_end'])}", "요청 시각(KST)": kst(r["requested_at"]),
                           "요청자": r["actor"], "시도": r["attempt"], "읽는 곳": r["source"]} for r in requests])
    st.dataframe(table, hide_index=True, width="stretch")
else:
    st.caption("최근 24시간 요청이 없습니다.")
st.button("새로고침", on_click=clear_caches)
st.caption("단계별 전체 이력은 '재처리 이력' 화면에서 봅니다. 승인한 요청이 재처리되는 동안 상태가 바뀌면 새로고침하세요.")
