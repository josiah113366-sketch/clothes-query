"""이상탐지·원인 리포트 화면 실데이터 연결 시험 (2026-10-25, 탐지 담당 직접 연결).

진짜 Athena 대신 가짜 조회 함수로 SQL·칸·형식을 보고, 실제 모양의 데이터(Athena처럼 값이 모두 글자)로 화면을 연다.
test_gold_b_data.py와 같은 방식을 쓴다.

실행: python test_anomaly_rca_data.py   (dashboard 폴더에서. 화면 시험은 streamlit이 있어야 한다)
"""
import importlib
import json
import os
import sys
import types

import pandas as pd
import streamlit as st

import data

ok = True
NEW = ["get_anomalies", "get_rca_reports"]
NOW = pd.Timestamp("2026-10-25 09:00:00", tz="UTC")


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


class FakeAthena:
    """data._athena 처럼 값이 모두 글자인 DataFrame을 돌려주고 받은 SQL을 남긴다."""

    def __init__(self, columns, rows):
        self.columns, self.rows, self.sql = columns, rows, []

    def __call__(self, sql):
        self.sql.append(sql)
        return pd.DataFrame([[None if v is None else str(v) for v in r] for r in self.rows], columns=self.columns)


def is_utc(s):
    return isinstance(s.dtype, pd.DatetimeTZDtype) and str(s.dtype.tz) == "UTC"


ANOMALY_COLS = ["anomaly_id", "rule_id", "anomaly_type", "scope_key", "observed_value", "baseline_value", "status", "detected_at"]
ANOMALIES = [
    ("a-1", "R1_PG_FAILURES", "PG_FAILURE_SPIKE", "PG_A", 12.0, 3.0, "OPEN", "2026-10-25 08:30:00.000"),
    ("a-2", "R6_ORDER_TOTAL_MISMATCH", "ORDER_TOTAL_MISMATCH", "orders", 30.0, 0.0, "RESOLVED", "2026-10-24 19:04:38.000"),
]
RCA_COLS = ["report_id", "anomaly_id", "rule_id", "scope_key", "anomaly_detected_at",
            "created_at", "cause_layer", "conclusion", "claims", "problems", "model_id"]
RCA = [
    ("rep-1", "a-1", "R1_PG_FAILURES", "PG_A", "2026-10-25 08:30:00.000", "2026-10-25 08:35:00.000",
     "PAYMENT", "PG_A 실패 급증", json.dumps([{"text": "실패 비율 61%", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]},
                                            {"text": "원인 미확인", "kind": "ASSUMPTION", "evidence": []}], ensure_ascii=False),
     json.dumps([], ensure_ascii=False), "jp.anthropic.claude-haiku-4-5-v1:0"),
]

# --- 등록 ---
check("workgroup 환경변수가 없으면 등록하지 않음", sorted(k for k in data._REAL if k in NEW), [])
dummy_columns = {name: list(getattr(data, name)().columns) for name in NEW}
check("이상탐지 더미 칸", dummy_columns["get_anomalies"], ANOMALY_COLS)
check("원인 리포트 더미 칸", dummy_columns["get_rca_reports"], RCA_COLS)

# --- 이상탐지 ---
q = FakeAthena(ANOMALY_COLS, ANOMALIES)
an = data._real_anomalies(48, query=q, now=NOW)
check("이상탐지: 더미와 같은 칸", list(an.columns), dummy_columns["get_anomalies"])
check("이상탐지: 시각은 UTC, 관측값·기준값은 숫자",
      (is_utc(an.detected_at), pd.api.types.is_numeric_dtype(an.observed_value),
       pd.api.types.is_numeric_dtype(an.baseline_value)), (True, True, True))
check("이상탐지: anomaly_current 최근 48시간",
      ("FROM gold_b.anomaly_current" in q.sql[0], "detected_at >= TIMESTAMP '2026-10-23 09:00:00'" in q.sql[0]),
      (True, True))
empty = data._real_anomalies(48, query=FakeAthena(ANOMALY_COLS, []), now=NOW)
check("이상탐지: 결과가 없으면 칸만 있는 빈 표 (이상 없음 = 정상)", (len(empty), list(empty.columns)), (0, dummy_columns["get_anomalies"]))

# --- 원인 리포트 ---
q = FakeAthena(RCA_COLS, RCA)
rca = data._real_rca_reports(7, query=q, now=NOW)
check("원인 리포트: 더미와 같은 칸", list(rca.columns), dummy_columns["get_rca_reports"])
check("원인 리포트: 시각 2개가 UTC, claims·problems는 파이썬 목록으로 풀림",
      (is_utc(rca.created_at), is_utc(rca.anomaly_detected_at),
       rca.claims.iloc[0] == [{"text": "실패 비율 61%", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]},
                              {"text": "원인 미확인", "kind": "ASSUMPTION", "evidence": []}],
       rca.problems.iloc[0] == []),
      (True, True, True, True))
check("원인 리포트: investigation_reports를 anomaly_current와 합치고, dt는 문자열 비교로 최근 7일",
      ("FROM agent.investigation_reports r" in q.sql[0], "JOIN gold_b.anomaly_current a ON a.anomaly_id = r.anomaly_id" in q.sql[0],
       "r.dt >= '2026-10-18'" in q.sql[0]), (True, True, True))
for missing in (None, float("nan"), pd.NA, ""):
    # Athena NULL becomes NaN in some pandas versions when mixed with JSON strings.
    frame = FakeAthena(RCA_COLS, RCA)("fixture").astype(object)
    frame.at[0, "problems"] = missing
    decoded = data._real_rca_reports(7, query=lambda sql: frame.copy(), now=NOW)
    check(f"nullable report problems: {missing!r}", decoded.problems.iloc[0], [])
    check("nullable problems preserves claims", decoded.claims.iloc[0], rca.claims.iloc[0])

empty_rca = data._real_rca_reports(7, query=FakeAthena(RCA_COLS, []), now=NOW)
check("원인 리포트: 결과가 없으면 빈 표 (아직 조사 전 = 정상)", len(empty_rca), 0)

# --- workgroup이 있으면 등록, 조회가 실패하면 더미로 대체 ---
os.environ["DASHBOARD_ATHENA_WORKGROUP"] = "wg-test"
importlib.reload(data)
check("workgroup이 있으면 두 화면이 등록됨", sorted(k for k in data._REAL if k in NEW), sorted(NEW))
del os.environ["DASHBOARD_ATHENA_WORKGROUP"]
importlib.reload(data)


def broken(*args, **kwargs):
    raise RuntimeError("권한 없음 (시험)")


data._REAL["get_anomalies"] = broken
st.cache_data.clear()
fallback = data.get_anomalies()
check("조회가 실패하면 더미로 대체하고 더미 목록에 넣음",
      (len(fallback) > 0, "get_anomalies" in data.USING_DUMMY), (True, True))
data._REAL.clear()
data.USING_DUMMY.clear()

# --- 화면 (streamlit이 있을 때만) ---
try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    print("건너뜀 화면 시험: streamlit이 없음")
else:
    real = {
        "get_anomalies": lambda: data._real_anomalies(48, query=FakeAthena(ANOMALY_COLS, ANOMALIES), now=NOW),
        "get_rca_reports": lambda: data._real_rca_reports(7, query=FakeAthena(RCA_COLS, RCA), now=NOW),
    }
    cases = [(page, label, registered) for label, registered in (("더미", {}), ("비어 있음(정상)", {
        "get_anomalies": lambda: data._real_anomalies(48, query=FakeAthena(ANOMALY_COLS, []), now=NOW),
        "get_rca_reports": lambda: data._real_rca_reports(7, query=FakeAthena(RCA_COLS, []), now=NOW),
    }), ("실데이터 모양", real)) for page in ("pages_data/anomaly.py", "pages_data/rca_report.py")]
    for page, label, registered in cases:
        data._REAL.clear()
        data._REAL.update(registered)
        data.USING_DUMMY.clear()
        st.cache_data.clear()
        at = AppTest.from_file(page, default_timeout=30).run()
        check(f"화면 {page} ({label}): 오류 없이 열림", [str(e.value) for e in at.exception], [])

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
