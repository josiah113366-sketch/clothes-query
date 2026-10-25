"""Gold B 화면 실데이터 연결 시험 (결제 관제·형식 오류·재처리 이력, TODO B1).

진짜 Athena 대신 가짜 조회 함수로 SQL·칸·형식을 보고, 실제 모양의 데이터(Athena처럼 값이 모두 글자, copies 없음)로
화면을 연다. 지연(파이프라인 상태)은 #107이 연결한 것이라 여기서는 화면이 열리는지만 본다.

실행: python test_gold_b_data.py   (dashboard 폴더에서. 화면 시험은 streamlit이 있어야 한다)
"""
import importlib
import os
import sys
import types

import pandas as pd
import streamlit as st

import data

ok = True
NEW = ["get_malformed_events", "get_payment_attempts", "get_reprocess_events"]
NOW = pd.Timestamp("2026-10-24 05:30:00", tz="UTC")


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


class FakeAthena:
    """data._athena 처럼 값이 모두 글자인 DataFrame 을 돌려주고 받은 SQL을 남긴다."""

    def __init__(self, columns, rows):
        self.columns, self.rows, self.sql = columns, rows, []

    def __call__(self, sql):
        self.sql.append(sql)
        return pd.DataFrame([[None if v is None else str(v) for v in r] for r in self.rows], columns=self.columns)


def is_utc(s):
    return str(s.dtype) == "datetime64[ns, UTC]"


ATTEMPT_COLS = ["payment_id", "order_id", "attempt_no", "pg", "status", "failure_code", "failure_cause",
                "completed_at", "loaded_at"]
ATTEMPTS = [
    ("p-1", "o-1", 1, "PG_A", "SUCCESS", None, None, "2026-10-24 05:01:00.000", "2026-10-24 05:01:40.000"),
    ("p-2", "o-2", 1, "PG_A", "FAILED", "PG_TIMEOUT", "PG", "2026-10-24 05:02:00.000", "2026-10-24 05:02:40.000"),
    ("p-3", "o-3", 2, "PG_B", "FAILED", "CARD_DECLINED", "CUSTOMER", "2026-10-24 05:03:00.000", "2026-10-24 05:03:40.000"),
]
MALFORMED_COLS = ["topic", "kafka_partition", "kafka_offset", "kafka_timestamp", "field", "reason", "rule_version"]
MALFORMED = [
    ("clickstream", 0, 18001, "2026-10-24 05:10:00.000", "session_id", "MISSING_FIELD", "0.2.0"),
    ("clickstream", 0, 18001, "2026-10-24 05:10:00.000", "event_time", "TYPE_MISMATCH", "0.2.0"),
    ("payments", 1, 204, "2026-10-24 05:20:00.000", "pg", "INVALID_VALUE", "0.2.0"),
]
REPROCESS_COLS = ["request_id", "step", "at", "actor", "window_start", "window_end", "rule_version", "source"]
REPROCESS = [
    ("rq-1", step, at, actor, "2026-10-24 01:00:00.000", "2026-10-24 02:00:00.000", "0.2.0", source)
    for step, at, actor, source in [("REQUESTED", "2026-10-24 03:00:00.000", "jh@example.com", "KAFKA"),
                                    ("APPROVED", "2026-10-24 03:05:00.000", "jh@example.com", "KAFKA"),
                                    ("STARTED", "2026-10-24 03:06:00.000", "reprocess_job", "KAFKA"),
                                    ("LEDGER_REPLACED", "2026-10-24 03:07:00.000", "reprocess_job", "KAFKA")]
]

# --- 등록 ---
check("workgroup 환경변수가 없으면 등록하지 않음", sorted(k for k in data._REAL if k in NEW), [])
dummy_columns = {name: list(getattr(data, name)(*args).columns)
                 for name, args in [("get_payment_attempts", (6,)), ("get_malformed_events", ()),
                                    ("get_reprocess_events", ())]}
check("결제 시도 더미에도 copies 칸이 없음 (뷰와 같게)", "copies" in dummy_columns["get_payment_attempts"], False)

# --- 결제 시도 ---
q = FakeAthena(ATTEMPT_COLS, ATTEMPTS)
att = data._real_payment_attempts(6, query=q, now=NOW)
check("결제 시도: 더미와 같은 칸", list(att.columns), dummy_columns["get_payment_attempts"])
check("결제 시도: 시각은 UTC 시각, 시도 번호는 숫자",
      (is_utc(att.completed_at), is_utc(att.loaded_at), pd.api.types.is_numeric_dtype(att.attempt_no)), (True, True, True))
check("결제 시도: 뷰에서 최근 6시간",
      ("FROM gold_b.payment_attempts" in q.sql[0], "completed_at >= TIMESTAMP '2026-10-23 23:30:00'" in q.sql[0]),
      (True, True))
empty = data._real_payment_attempts(6, query=FakeAthena(ATTEMPT_COLS, []), now=NOW)
check("결제 시도: 결과가 없으면 칸만 있는 빈 표", (len(empty), list(empty.columns)), (0, dummy_columns["get_payment_attempts"]))

# --- 형식 오류 ---
q = FakeAthena(MALFORMED_COLS, MALFORMED)
mal = data._real_malformed_events(query=q, now=NOW)
check("형식 오류: 더미와 같은 칸", list(mal.columns), dummy_columns["get_malformed_events"])
check("형식 오류: 시각은 UTC 시각, 위치는 숫자",
      (is_utc(mal.kafka_timestamp), pd.api.types.is_numeric_dtype(mal.kafka_offset)), (True, True))
check("형식 오류: 최근 6시간의 시간 폴더만 읽음 (전날 23시 ~ 05시, 자정 넘김)",
      ("FROM gold_b.malformed_events" in q.sql[0], "(dt = '2026-10-23' AND hour = '23')" in q.sql[0],
       "(dt = '2026-10-24' AND hour = '05')" in q.sql[0], "(dt = '2026-10-23' AND hour = '22')" in q.sql[0],
       "kafka_timestamp >= TIMESTAMP '2026-10-23 23:30:00'" in q.sql[0]), (True, True, True, False, True))
check("형식 오류: 깨진 메시지는 위치 기준으로 셈 (오류 3줄 = 메시지 2개)", len(data.to_malformed_messages(mal)), 2)

# --- 재처리 기록 ---
q = FakeAthena(REPROCESS_COLS, REPROCESS)
rep = data._real_reprocess_events(query=q, now=NOW)
check("재처리 기록: 더미와 같은 칸", list(rep.columns), dummy_columns["get_reprocess_events"])
check("재처리 기록: 시각 칸 3개가 UTC 시각", [is_utc(rep[c]) for c in ("at", "window_start", "window_end")], [True] * 3)
check("재처리 기록: 최근 7일, at 칸은 따옴표로",
      ("FROM gold_b.reprocess_events" in q.sql[0], "\"at\" >= TIMESTAMP '2026-10-17 05:30:00'" in q.sql[0],
       'ORDER BY "at"' in q.sql[0]), (True, True, True))

# --- workgroup 이 있으면 지연과 함께 등록, 조회가 실패하면 더미로 대체 ---
os.environ["DASHBOARD_ATHENA_WORKGROUP"] = "wg-test"
importlib.reload(data)
check("workgroup 이 있으면 지연과 함께 4개 등록",
      sorted(k for k in data._REAL if k in NEW + ["get_bronze_lag"]), sorted(NEW + ["get_bronze_lag"]))
del os.environ["DASHBOARD_ATHENA_WORKGROUP"]
importlib.reload(data)


def broken(*args, **kwargs):
    raise RuntimeError("권한 없음 (시험)")


data._REAL["get_payment_attempts"] = broken
st.cache_data.clear()   # 앞에서 더미 칸을 보려고 부른 결과가 남아 있다
fallback = data.get_payment_attempts(6)
check("조회가 실패하면 더미로 대체하고 더미 목록에 넣음",
      (len(fallback) > 0, "get_payment_attempts" in data.USING_DUMMY), (True, True))
EMPTY = {   # 실데이터 연결은 됐는데 결과가 0건인 경우 (형식 오류·재처리 기록은 평소 0건이 정상)
    "get_malformed_events": lambda: data._real_malformed_events(query=FakeAthena(MALFORMED_COLS, []), now=NOW),
    "get_reprocess_events": lambda: data._real_reprocess_events(query=FakeAthena(REPROCESS_COLS, []), now=NOW),
}
data._REAL.update(EMPTY)
data.USING_DUMMY.clear()
st.cache_data.clear()
check("빈 실데이터: 형식 오류·재처리 기록은 더미 대신 빈 표 그대로 (화면에 0건)",
      (len(data.get_malformed_events()), len(data.get_reprocess_events()), sorted(data.USING_DUMMY)), (0, 0, []))
data._REAL["get_malformed_events"] = broken
st.cache_data.clear()
check("형식 오류도 조회가 실패하면 더미로 대체",
      (len(data.get_malformed_events()) > 0, "get_malformed_events" in data.USING_DUMMY), (True, True))
data._REAL.clear()
data.USING_DUMMY.clear()

# --- 화면 (streamlit이 있을 때만) ---
try:
    import streamlit_echarts  # noqa: F401
except ImportError:   # 그래프 패키지(#107)가 없으면 그리기만 빈 함수로 대신하고, 화면의 데이터 처리는 그대로 본다
    stub = types.ModuleType("streamlit_echarts")
    stub.JsCode = lambda code: code
    stub.st_echarts = lambda *args, **kwargs: None
    sys.modules["streamlit_echarts"] = stub
    print("알림: streamlit_echarts가 없어 그래프 그리기는 빈 함수로 대신함")
try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    print("건너뜀 화면 시험: streamlit이 없음")
else:
    only_success = [r for r in ATTEMPTS if r[4] == "SUCCESS"]
    real = {
        "get_payment_attempts": lambda hours=6: data._real_payment_attempts(hours, query=FakeAthena(ATTEMPT_COLS, ATTEMPTS), now=NOW),
        "get_malformed_events": lambda: data._real_malformed_events(query=FakeAthena(MALFORMED_COLS, MALFORMED), now=NOW),
        "get_reprocess_events": lambda: data._real_reprocess_events(query=FakeAthena(REPROCESS_COLS, REPROCESS), now=NOW),
    }
    no_failures = {"get_payment_attempts": lambda hours=6: data._real_payment_attempts(
        hours, query=FakeAthena(ATTEMPT_COLS, only_success), now=NOW)}
    note = "※ 현재는 더미 데이터입니다"
    cases = [(page, label, registered) for label, registered in (("더미", {}), ("실데이터 모양", real))
             for page in ("pages_data/payments.py", "pages_data/malformed.py", "pages_data/reprocess.py")]
    cases.append(("pages_data/payments.py", "실패 없는 실데이터", no_failures))
    for page, label, registered in cases:
        data._REAL.clear()
        data._REAL.update(registered)
        data.USING_DUMMY.clear()
        st.cache_data.clear()
        at = AppTest.from_file(page, default_timeout=30).run()
        check(f"화면 {page} ({label}): 오류 없이 열림", [str(e.value) for e in at.exception], [])
        check(f"화면 {page} ({label}): 더미 안내는 더미일 때만",
              any(c.value.startswith(note) for c in at.caption), label == "더미")
    for page, want in (("pages_data/malformed.py", "형식 오류가 없습니다 (0건)"),
                       ("pages_data/reprocess.py", "재처리 기록이 없습니다 (0건)")):
        data._REAL.clear()
        data._REAL.update(EMPTY)
        data.USING_DUMMY.clear()
        st.cache_data.clear()
        at = AppTest.from_file(page, default_timeout=30).run()
        check(f"화면 {page} (빈 실데이터): 오류 없이 열림", [str(e.value) for e in at.exception], [])
        shown = [str(e.value) for e in list(at.success) + list(at.info)]
        check(f"화면 {page} (빈 실데이터): 더미 대신 0건 안내, 더미 안내 없음",
              (any(want in s for s in shown), any(c.value.startswith(note) for c in at.caption)), (True, False))
    data._REAL.clear()
    st.cache_data.clear()
    at = AppTest.from_file("pages_data/pipeline.py", default_timeout=30).run()
    check("화면 pages_data/pipeline.py (더미, #107 화면): 오류 없이 열림", [str(e.value) for e in at.exception], [])

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
