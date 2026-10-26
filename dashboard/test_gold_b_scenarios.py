"""시나리오 2·3 화면 시험: 토픽별 유입(파이프라인 상태), 성공 결제가 2건 이상인 주문(결제 관제).

진짜 Athena 대신 가짜 조회 함수로 SQL·칸·형식을 보고, "비면 더미" 규칙에서 뺀 두 함수(allow_empty)가 빈 결과를
그대로 돌려주는지, 조회가 실패하면 더미로 대체하는지, 두 화면이 더미·실제 모양·빈 데이터로 열리는지 본다.

실행: python test_gold_b_scenarios.py   (dashboard 폴더에서. 화면 시험은 streamlit이 있어야 한다)
"""
import importlib
import os
import sys
import types

import pandas as pd
import streamlit as st

import data

ok = True
NEW = ["get_duplicate_success", "get_topic_inflow"]
NOW = pd.Timestamp("2026-10-24 05:30:20", tz="UTC")


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


DUP_COLS = ["order_id", "success_count", "payment_ids", "pgs", "first_completed_at", "last_completed_at",
            "last_loaded_at"]
DUP = [("o-1", 2, "p-1,p-9", "PG_A", "2026-10-24 01:00:00.000", "2026-10-24 01:00:02.000", "2026-10-24 05:20:00.000")]
INFLOW_COLS = ["minute", "topic", "messages"]
INFLOW = [(f"2026-10-24 05:{m:02d}:00.000", topic, n * (5 if m >= 20 else 1))
          for m in range(10, 29) for topic, n in (("clickstream", 2000), ("payments", 20))]

# --- 등록 ---
check("workgroup 환경변수가 없으면 등록하지 않음", sorted(k for k in data._REAL if k in NEW), [])
os.environ["DASHBOARD_ATHENA_WORKGROUP"] = "wg-test"
importlib.reload(data)
check("workgroup 이 있으면 두 함수도 등록", sorted(k for k in data._REAL if k in NEW), NEW)
del os.environ["DASHBOARD_ATHENA_WORKGROUP"]
importlib.reload(data)
dummy_dup, dummy_inflow = data.get_duplicate_success(6), data.get_topic_inflow(180)

# --- 성공 결제 중복 ---
q = FakeAthena(DUP_COLS, DUP)
dup = data._real_duplicate_success(6, query=q, now=NOW)
check("성공 결제 중복: 더미와 같은 칸", list(dup.columns), list(dummy_dup.columns))
check("성공 결제 중복: 건수는 숫자, 시각 3개는 UTC 시각",
      (pd.api.types.is_numeric_dtype(dup.success_count), [is_utc(dup[c]) for c in DUP_COLS[4:]]), (True, [True] * 3))
check("성공 결제 중복: 뷰에서 최근 6시간 '적재'된 성공 결제의 주문, 성공 2건 이상 (판정 R5와 같은 방식)",
      ("FROM gold_b.payment_attempts" in q.sql[0], "loaded_at >= TIMESTAMP '2026-10-23 23:30:20'" in q.sql[0],
       "loaded_at < TIMESTAMP '2026-10-24 05:30:20'" in q.sql[0], "HAVING count(*) > 1" in q.sql[0],
       "completed_at >=" in q.sql[0]), (True, True, True, True, False))

# --- 토픽별 유입 ---
q = FakeAthena(INFLOW_COLS, INFLOW)
inflow = data._real_topic_inflow(180, query=q, now=NOW)
check("유입: 더미와 같은 칸", list(inflow.columns), list(dummy_inflow.columns))
check("유입: 분은 UTC 시각, 건수는 숫자", (is_utc(inflow.minute), pd.api.types.is_numeric_dtype(inflow.messages)),
      (True, True))
check("유입: 시간 폴더 조건(02~05시)과 덜 찬 지금 분·직전 분 빼기 (05:29 전까지)",
      ("FROM gold_b.topic_messages" in q.sql[0], "(dt = '2026-10-24' AND hour = '02')" in q.sql[0],
       "(dt = '2026-10-24' AND hour = '05')" in q.sql[0], "hour = '01'" in q.sql[0],
       "kafka_timestamp >= TIMESTAMP '2026-10-24 02:29:00'" in q.sql[0],
       "kafka_timestamp < TIMESTAMP '2026-10-24 05:29:00'" in q.sql[0]), (True, True, True, False, True, True))

# --- 비어도 더미로 바꾸지 않음 (allow_empty), 실패하면 더미 ---
data._REAL.update({
    "get_duplicate_success": lambda hours=6, end=None: data._real_duplicate_success(
        hours, end, query=FakeAthena(DUP_COLS, [])),
    "get_topic_inflow": lambda minutes=180, end=None: data._real_topic_inflow(
        minutes, end, query=FakeAthena(INFLOW_COLS, [])),
    "get_payment_attempts": lambda hours=6, end=None: pd.DataFrame(
        columns=list(data.get_payment_attempts.__wrapped__(6).columns)),
})
data.USING_DUMMY.clear()
st.cache_data.clear()
check("빈 실데이터: 성공 결제 중복·유입은 빈 표 그대로 (더미 목록에 없음)",
      (len(data.get_duplicate_success(6)), len(data.get_topic_inflow(180)), sorted(data.USING_DUMMY)), (0, 0, []))
check("빈 실데이터: 결제 시도는 지금처럼 더미로 대체 (allow_empty 아님)",
      (len(data.get_payment_attempts(6)) > 0, "get_payment_attempts" in data.USING_DUMMY), (True, True))


def broken(*args, **kwargs):
    raise RuntimeError("권한 없음 (시험)")


data._REAL["get_topic_inflow"] = broken
st.cache_data.clear()
check("조회가 실패하면 유입도 더미로 대체하고 더미 목록에 넣음",
      (len(data.get_topic_inflow(180)) > 0, "get_topic_inflow" in data.USING_DUMMY), (True, True))
data._REAL.clear()
data.USING_DUMMY.clear()

# --- 화면 (streamlit이 있을 때만) ---
try:
    import streamlit_echarts  # noqa: F401
except ImportError:   # 그래프 패키지가 없으면 그리기만 빈 함수로 대신하고, 화면의 데이터 처리는 그대로 본다
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
    def page(path, registered):
        data._REAL.clear()
        data._REAL.update(registered)
        data.USING_DUMMY.clear()
        st.cache_data.clear()
        return AppTest.from_file(path, default_timeout=30).run()

    def texts(elements):
        return [str(e.value) for e in elements]

    dup_note = "※ 이 칸은 더미 데이터입니다."
    real_dup = {"get_duplicate_success": lambda hours=6, end=None: data._real_duplicate_success(
        hours, end, query=FakeAthena(DUP_COLS, DUP))}
    empty_dup = {"get_duplicate_success": lambda hours=6, end=None: data._real_duplicate_success(
        hours, end, query=FakeAthena(DUP_COLS, []))}
    for label, registered, want in (("더미", {}, ("2건", True)), ("실데이터 모양", real_dup, ("1건", False)),
                                    ("빈 실데이터", empty_dup, (None, False))):
        at = page("pages_data/payments.py", registered)
        check(f"결제 관제 ({label}): 오류 없이 열림", texts(at.exception), [])
        errors = [t for t in texts(at.error) if "성공 결제가 2건 이상인 주문" in t]
        check(f"결제 관제 ({label}): 성공 결제 2건 이상 주문 경고",
              (errors[0].split("주문 ")[1].split(":")[0] if errors else None, dup_note in texts(at.caption)), want)
        if label == "빈 실데이터":
            check("결제 관제 (빈 실데이터): 정상 안내", any("없습니다 (정상)" in t for t in texts(at.success)), True)

    real_inflow = {"get_topic_inflow": lambda minutes=180, end=None: data._real_topic_inflow(
        minutes, end, query=FakeAthena(INFLOW_COLS, INFLOW))}
    empty_inflow = {"get_topic_inflow": lambda minutes=180, end=None: data._real_topic_inflow(
        minutes, end, query=FakeAthena(INFLOW_COLS, []))}
    for label, registered in (("더미", {}), ("실데이터 모양", real_inflow), ("빈 실데이터", empty_inflow)):
        at = page("pages_data/pipeline.py", registered)
        check(f"파이프라인 상태 ({label}): 오류 없이 열림", texts(at.exception), [])
        captions = texts(at.caption)
        check(f"파이프라인 상태 ({label}): 더미 안내에 '유입'은 더미일 때만",
              any(c.startswith("※ 지금 더미 데이터") and "유입" in c for c in captions), label == "더미")
        check(f"파이프라인 상태 ({label}): 최근 1분 건수 또는 '메시지 없음' 경고",
              (any(c.startswith("최근 1분 건수") for c in captions),
               any("메시지가 없습니다" in w for w in texts(at.warning))), (label != "빈 실데이터", label == "빈 실데이터"))
    at = page("pages_data/pipeline.py", real_inflow)
    last = next(c for c in texts(at.caption) if c.startswith("최근 1분 건수"))
    check("파이프라인 상태: 최근 1분 건수는 마지막 분 값 (clickstream 10,000, payments 100)",
          ("clickstream 10,000" in last, "payments 100" in last), (True, True))
    data._REAL.clear()

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
