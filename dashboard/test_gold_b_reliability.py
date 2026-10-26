"""원장 신뢰성 점검 칸 시험 (파이프라인 상태 > 지연·점검, TODO B3).

진짜 Athena 대신 가짜 조회 함수로 SQL(표, 시간 폴더, 덜 찬 분 빼기)과 점검 판정(정상 / 확인 필요 / 문제)을 보고,
화면이 정상·문제·더미일 때 경고와 더미 안내를 맞게 보여 주는지 본다.

실행: python test_gold_b_reliability.py   (dashboard 폴더에서. 화면 시험은 streamlit이 있어야 한다)
"""
import importlib
import os
import sys
import types

import pandas as pd
import streamlit as st

import data

ok = True
NOW = pd.Timestamp("2026-10-24 05:30:20", tz="UTC")
COLS = ["missing_offsets", "gap_partitions", "partitions_seen", "partitions_expected", "duplicate_rows",
        "duplicate_payment_ids", "load_late_sec", "load_late_at", "collect_gap_sec", "collect_gap_end",
        "last_loaded", "last_collected"]
NORMAL = {"missing_offsets": 0, "gap_partitions": 0, "partitions_seen": 15, "partitions_expected": 15,
          "duplicate_rows": 0, "duplicate_payment_ids": 0,
          "load_late_sec": 68, "load_late_at": "2026-10-24 05:20:00.000",   # 평소: 1분 묶음 + 처리 = 최대 약 68초
          "collect_gap_sec": 60, "collect_gap_end": "2026-10-24 05:30:01.000",
          "last_loaded": "2026-10-24 05:29:50.000", "last_collected": "2026-10-24 05:30:01.000"}


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


class FakeAthena:
    """data._athena 처럼 값이 모두 글자인 한 줄짜리 DataFrame 을 돌려주고 받은 SQL을 남긴다."""

    def __init__(self, **changes):
        self.row, self.sql = {**NORMAL, **changes}, []

    def __call__(self, sql):
        self.sql.append(sql)
        return pd.DataFrame([[None if self.row[c] is None else str(self.row[c]) for c in COLS]], columns=COLS)


def run(**changes):
    return data._real_reliability_checks(query=FakeAthena(**changes), now=NOW).set_index("check")


GAP, DUP, STALL = "오프셋 빈틈", "중복(같은 topic/partition/offset)", "적재 정지(2분 초과)"

# --- 등록 ---
check("workgroup 환경변수가 없으면 등록하지 않음", "get_reliability_checks" in data._REAL, False)
os.environ["DASHBOARD_ATHENA_WORKGROUP"] = "wg-test"
importlib.reload(data)
check("workgroup 이 있으면 등록", data._REAL.get("get_reliability_checks") is data._real_reliability_checks, True)
del os.environ["DASHBOARD_ATHENA_WORKGROUP"]
importlib.reload(data)

# --- SQL ---
q = FakeAthena()
normal = data._real_reliability_checks(query=q, now=NOW)
sql = q.sql[0]
check("한 번의 조회로 원장 3개를 읽음", (len(q.sql), "FROM gold_b.topic_messages" in sql,
                                 "FROM gold_b.bronze_lag_snapshots" in sql, "FROM gold_b.payment_events" in sql),
      (1, True, True, True))
check("최근 3시간, 덜 찬 지금 분·직전 분 빼기 (02:29 ~ 05:29), 시간 폴더 조건(02~05시)",
      ("kafka_timestamp >= TIMESTAMP '2026-10-24 02:29:00'" in sql, "kafka_timestamp < TIMESTAMP '2026-10-24 05:29:00'" in sql,
       "(dt = '2026-10-24' AND hour = '02')" in sql, "(dt = '2026-10-24' AND hour = '05')" in sql, "hour = '01'" in sql),
      (True, True, True, True, False))
check("빈틈은 offset 칸 수 - 고유 offset 수, 중복은 같은 위치 기준",
      ("(max(kafka_offset) - min(kafka_offset) + 1) - count(DISTINCT kafka_offset)" in sql,
       "count(DISTINCT concat(topic, '-', CAST(kafka_partition AS varchar), '-', CAST(kafka_offset AS varchar)))" in sql),
      (True, True))
check("적재 정지: 늦게 쓴 정도(loaded_at - kafka_timestamp), 지연 수집기 측정 간격(구간 시작·지금을 끝점으로)",
      ("max(date_diff('second', kafka_timestamp, loaded_at))" in sql, "lag(t) OVER (ORDER BY t)" in sql,
       "UNION ALL SELECT TIMESTAMP '2026-10-24 02:29:00' UNION ALL SELECT TIMESTAMP '2026-10-24 05:30:20'" in sql),
      (True, True, True))

# --- 판정 ---
check("더미와 같은 칸", list(normal.columns), list(data.get_reliability_checks.__wrapped__().columns))
r = normal.set_index("check")
check("정상: 세 점검 모두 정상", list(r.result), ["정상"] * 3)
check("정상: 설명에 숫자", (r.detail[GAP], r.detail[STALL]),
      ("최근 3시간 빈틈 0건 (파티션 15개)",
       "가장 늦게 쓴 메시지 68초 · 지연 수집기 측정 간격 최대 60초 · 마지막 기록 적재 잡 30초 전, 지연 수집기 19초 전"))
r = run(missing_offsets=3, gap_partitions=1)
check("빈틈이 있으면 문제", (r.result[GAP], r.detail[GAP]), ("문제", "최근 3시간 빈틈 3건 (파티션 1개)"))
r = run(partitions_seen=14)
check("빈틈은 없지만 메시지가 없는 파티션이 있으면 확인 필요",
      (r.result[GAP], r.detail[GAP]), ("확인 필요", "최근 3시간 메시지가 없는 파티션 1개 (보인 파티션 14/15개)"))
r = run(duplicate_rows=2)
check("같은 위치가 두 줄이면 문제", r.result[DUP], "문제")
r = run(duplicate_payment_ids=6)
check("같은 결제 번호만 겹치면 정상 (참고로만 적음)", (r.result[DUP], "같은 결제 번호 6건" in r.detail[DUP]), ("정상", True))
r = run(last_loaded="2026-10-24 05:25:20.000")
check("적재 잡이 2분 넘게 안 쓰면 문제", (r.result[STALL], r.detail[STALL].startswith("적재 잡 5분째 안 씀")), ("문제", True))
r = run(load_late_sec=420, load_late_at="2026-10-24 04:12:00.000")
check("구간 메시지를 2분 넘게 늦게 썼으면 문제 (지금은 다시 쓰고 있어도)",
      (r.result[STALL], r.detail[STALL].split(" · ")[0]), ("문제", "적재 잡이 10-24 13:12 KST 메시지를 7분 늦게 씀"))
r = run(collect_gap_sec=300, collect_gap_end="2026-10-24 04:00:00.000")
check("지연 수집기 측정 간격이 2분 넘은 적이 있으면 문제",
      (r.result[STALL], r.detail[STALL].split(" · ")[0]), ("문제", "지연 수집기 측정 간격 5분 (10-24 12:55~13:00 KST)"))
r = run(collect_gap_sec=300, collect_gap_end="2026-10-24 05:30:20.000", last_collected="2026-10-24 05:25:20.000")
check("지금까지 빈 측정은 한 번만 적음 (몇 분째 안 씀)",
      (r.result[STALL], r.detail[STALL].split(" · ")[0]), ("문제", "지연 수집기 5분째 안 씀"))
r = run(last_collected=None)
check("지연 수집기 기록이 없으면 문제", (r.result[STALL], "지연 수집기 최근 3시간 기록 없음" in r.detail[STALL]), ("문제", True))
r = run(last_loaded="2026-10-24 05:28:21.000")
check("2분 안(119초 전)이면 정상", r.result[STALL], "정상")

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
    def page(registered):
        data._REAL.clear()
        data._REAL.update(registered)
        data.USING_DUMMY.clear()
        st.cache_data.clear()
        return AppTest.from_file("pages_data/pipeline.py", default_timeout=30).run()

    def texts(elements):
        return [str(e.value) for e in elements]

    def reliability(**changes):
        return {"get_reliability_checks": lambda minutes=180, end=None: data._real_reliability_checks(
            minutes, end, query=FakeAthena(**changes), now=NOW)}

    warn = "원장 점검에 정상이 아닌 항목이 있습니다"
    note = "※ 지금 더미 데이터"
    for label, registered, want_warn, want_dummy in (
        ("더미", {}, False, True),
        ("실데이터 정상", reliability(), False, False),
        ("실데이터 문제", reliability(duplicate_rows=2, last_collected=None), True, False),
    ):
        at = page(registered)
        check(f"파이프라인 상태 ({label}): 오류 없이 열림", texts(at.exception), [])
        warnings = [w for w in texts(at.warning) if w.startswith(warn)]
        check(f"파이프라인 상태 ({label}): 원장 점검 경고, 더미 안내의 '원장 신뢰성 점검'",
              (bool(warnings), any(c.startswith(note) and "원장 신뢰성 점검" in c for c in texts(at.caption))),
              (want_warn, want_dummy))
        if want_warn:
            check("파이프라인 상태 (실데이터 문제): 경고에 정상이 아닌 점검 이름",
                  (DUP in warnings[0], STALL in warnings[0], GAP in warnings[0]), (True, True, False))
    real_all = {**reliability(),
                "get_bronze_lag": lambda minutes=180, end=None: data.get_bronze_lag.__wrapped__(minutes, end),
                "get_topic_inflow": lambda minutes=180, end=None: data.get_topic_inflow.__wrapped__(minutes, end)}
    at = page(real_all)
    check("파이프라인 상태 (지연·유입·점검 모두 실데이터): 빈 더미 안내를 띄우지 않음",
          [c for c in texts(at.caption) if c.startswith(note)], [])
    data._REAL.clear()

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
