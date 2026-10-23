"""재처리 승인 화면 시험. 연습 모드(가짜 저장소)로 연결 모듈과 화면을 돌려 본다 (진짜 Athena·Airflow는 아직 안 돌려 봤다).

실행: python test_approval_page.py   (dashboard 폴더에서. 화면 시험은 streamlit이 있어야 한다)
"""
import json
from datetime import datetime, timedelta

import approval_io as io

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


def code(fn):
    try:
        fn()
    except io.ApprovalError as e:
        return e.code
    return None


NOW = datetime(2026, 10, 23, 3, 0, 0)
b = io.make_backend({}, now=NOW)
check("환경변수가 없으면 연습 모드", b.mode, "PRACTICE")

# --- 후보 이상 ---
cands = io.load_candidates(b, NOW)
check("후보: 연습 이상 3건, 최근 것이 먼저", [c["rule_id"] for c in cands], ["R3_BRONZE_LAG", "R6_ORDER_TOTAL_MISMATCH", "R1_PG_FAILURES"])
check("후보: R3는 재처리 대상이 아니라 reprocessable False", {c["rule_id"]: c["reprocessable"] for c in cands},
      {"R3_BRONZE_LAG": False, "R6_ORDER_TOTAL_MISMATCH": True, "R1_PG_FAILURES": True})
check("후보: 48시간보다 오래된 이상은 빠짐", len(io.load_candidates(b, NOW + timedelta(hours=49))), 0)

# --- 리포트 ---
rep = io.load_report(b, "a-practice-r6")
check("리포트: 검증 미통과 리포트는 problems가 있음", (rep["cause_layer"], len(rep["problems"]), rep["claims"][0]["kind"]), ("DATA_QUALITY", 1, "FACT"))
check("리포트: 없는 이상은 None", io.load_report(b, "a-none"), None)
check("리포트: 이상한 id는 거절", code(lambda: io.load_report(b, "a' OR '1'='1")), "BAD_ID")

# --- 요청 -> 승인 ---
R6 = next(c for c in cands if c["rule_id"] == "R6_ORDER_TOTAL_MISMATCH")
R1 = next(c for c in cands if c["rule_id"] == "R1_PG_FAILURES")
me = "jh@example.com"
check("요청: 승인자가 이메일이 아니면 거절", code(lambda: io.ap.request_reprocess(R6, "rep-practice-2", "data_user", NOW, b.query, b.write, b.cfg)), "ACTOR_REQUIRED")
r6 = io.ap.request_reprocess(R6, "rep-practice-2", me, NOW, b.query, b.write, b.cfg)
check("요청: R6는 재처리로 안 풀릴 수 있다는 경고가 붙음", r6["warnings"], ["UNFIXABLE_BY_REPROCESS"])
reqs = io.load_requests(b, NOW)
check("현황: 요청 1건이 승인 대기, 경고·규칙·시도 번호가 보임", [(r["state"], r["rule_id"], r["attempt"], r["warnings"]) for r in reqs], [("REQUESTED", "R6_ORDER_TOTAL_MISMATCH", 1, ["UNFIXABLE_BY_REPROCESS"])])
check("요청: 같은 이상에 진행 중 요청이 있으면 중복 거절", code(lambda: io.ap.request_reprocess(R6, "rep-practice-2", me, NOW, b.query, b.write, b.cfg)), "DUPLICATE_REQUEST")
res = io.ap.approve(r6["request_id"], me, NOW + timedelta(minutes=5), b.query, b.write, b.trigger, b.cfg)
check("승인: R6는 Airflow를 부름(연습은 가짜 호출)", res["airflow"], "TRIGGERED")
check("승인: 현황의 상태가 승인됨", io.load_requests(b, NOW + timedelta(minutes=6))[0]["state"], "APPROVED")
check("승인: 같은 요청을 다시 승인해도 중복 줄 없이 이미 시작으로 처리", io.ap.approve(r6["request_id"], me, NOW + timedelta(minutes=7), b.query, b.write, b.trigger, b.cfg)["airflow"], "TRIGGERED")
check("승인: APPROVED 줄은 한 줄뿐", len([r for r in b.query("SELECT step FROM gold_b.reprocess_events") if r["step"] == "APPROVED"]), 1)

# --- 요청 -> 거절, R1은 poller ---
r1 = io.ap.request_reprocess(R1, "rep-practice-1", me, NOW, b.query, b.write, b.cfg)
check("거절: 이유와 함께 거절됨", io.ap.reject(r1["request_id"], me, "원인을 아직 못 고침", NOW + timedelta(minutes=1), b.query, b.write, b.cfg)["state"], "REJECTED")
check("거절 뒤 승인은 상태 오류", code(lambda: io.ap.approve(r1["request_id"], me, NOW + timedelta(minutes=2), b.query, b.write, b.trigger, b.cfg)), "BAD_STATE")
r1b = io.ap.request_reprocess(R1, "rep-practice-1", me, NOW + timedelta(minutes=3), b.query, b.write, b.cfg)
check("R1 승인: poller 방식이라 Airflow를 부르지 않음", io.ap.approve(r1b["request_id"], me, NOW + timedelta(minutes=4), b.query, b.write, b.trigger, b.cfg)["airflow"], "POLLER")
check("현황: 요청 3건", len(io.load_requests(b, NOW + timedelta(minutes=5))), 3)
check("승인 대기가 60분 지나면 요청 만료", [r["state"] for r in io.load_requests(b, NOW + timedelta(minutes=70)) if r["request_id"] == r1b["request_id"]][0], "EXPIRED_APPROVAL")

# --- 실제 모드 만들기: 환경변수가 있어도 Airflow 접속 정보가 없으면 호출은 실패로 ---
class FakeAthena:
    def __init__(self, workgroup, database, region=None):
        self.workgroup = workgroup

    def query(self, sql):
        return []

    def write(self, table, rows):
        pass


io._load("agent_athena_io", io._agent_dir() / "detect" / "athena_io.py").AthenaIO = FakeAthena
real = io.make_backend({"APPROVAL_ATHENA_WORKGROUP": "wg"}, now=NOW)
check("실제 모드: Airflow 접속 정보가 없으면 호출은 0(실패)", (real.mode, real.trigger("d", "r", {})), ("REAL", 0))

# --- 화면 (streamlit이 있을 때만) ---
try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    print("건너뜀 화면 시험: streamlit이 없음")
else:
    at = AppTest.from_file("pages_data/approval.py", default_timeout=30).run()
    check("화면: 오류 없이 열림", [str(e.value) for e in at.exception], [])
    check("화면: 연습 모드 안내가 보임", any("연습 모드" in w.value for w in at.warning), True)
    check("화면: 승인 대기가 없으면 안내, 요청 버튼은 이상을 고르면 눌림", (any("승인을 기다리는 요청이 없습니다" in i.value for i in at.info), [x.label for x in at.button if x.label == "재처리 요청"]), (True, ["재처리 요청"]))
    req_btn = next(x for x in at.button if x.label == "재처리 요청")
    at.selectbox[0].select("a-practice-r6").run()          # R6 이상을 고름
    next(x for x in at.button if x.label == "재처리 요청").click().run()
    check("화면: 요청하면 성공 안내와 R6 경고", (any("요청했습니다" in s.value for s in at.success), any("원본을 먼저" in w.value or "원본" in w.value for w in at.warning)), (True, True))
    approve = next(x for x in at.button if x.label == "승인")
    check("화면: 확인 칸을 체크하기 전에는 승인 버튼이 막혀 있음", approve.disabled, True)
    at.checkbox[0].check().run()
    next(x for x in at.button if x.label == "승인").click().run()
    check("화면: 승인하면 시작 안내", any("승인했습니다" in s.value for s in at.success), True)
    check("화면: 승인 뒤 오류 없음", [str(e.value) for e in at.exception], [])

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
