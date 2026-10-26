"""조회 구간(과거 조회) 시험 (파이프라인 상태 › 지연·점검, 결제 관제, 형식 오류, TODO B11).

진짜 Athena 대신 가짜 조회 함수로 날짜를 지정한 구간의 SQL(시간 폴더, 시작·끝 조건, 지금보다 늦은 끝 자르기)과
신뢰성 점검의 과거 구간 판정을 본다. 화면에서 '날짜 지정'을 고르면 조회 함수가 그 구간으로 불리는지,
과거 구간이 비면 더미 대신 '기록 없음'이 보이는지도 본다.

실행: python test_gold_b_time_range.py   (dashboard 폴더에서. 화면 시험은 streamlit이 있어야 한다)
"""
import sys
import types

import pandas as pd
import streamlit as st

import data

ok = True
NOW = pd.Timestamp("2026-10-24 05:30:20", tz="UTC")
END = pd.Timestamp("2026-10-23 06:00:00", tz="UTC")  # 날짜 지정 끝 = 10-23 15:00 KST
H2 = pd.Timedelta(hours=2)


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


LAG_COLS = ["collected_at", "topic", "kafka_partition", "end_offset", "committed_offset", "lag_msgs", "lag_sec",
            "connector_state"]
INFLOW_COLS = ["minute", "topic", "messages"]
ATTEMPT_COLS = ["payment_id", "order_id", "attempt_no", "pg", "status", "failure_code", "failure_cause",
                "completed_at", "loaded_at"]
DUP_COLS = ["order_id", "success_count", "payment_ids", "pgs", "first_completed_at", "last_completed_at",
            "last_loaded_at"]
MALFORMED_COLS = ["topic", "kafka_partition", "kafka_offset", "kafka_timestamp", "field", "reason", "rule_version"]
REL = {"missing_offsets": 0, "gap_partitions": 0, "partitions_seen": 15, "partitions_expected": 15,
       "duplicate_rows": 0, "duplicate_payment_ids": 0,
       "load_late_sec": 68, "load_late_at": "2026-10-23 05:00:00.000",
       "collect_gap_sec": 60, "collect_gap_end": "2026-10-23 05:59:49.000",
       "last_loaded": "2026-10-23 05:59:50.000", "last_collected": "2026-10-23 05:59:49.000"}
GAP, STALL = "오프셋 빈틈", "적재 정지(2분 초과)"


def sql_of(fn, cols, *args):
    q = FakeAthena(cols, [])
    out = fn(*args, query=q, now=NOW)
    return q.sql[0], out


# --- 구간 ---
check("실시간: 지금까지 길이만큼", data._span(H2, None, NOW), (NOW - H2, NOW))
check("날짜 지정: 고른 끝까지 길이만큼", data._span(H2, END, NOW), (END - H2, END))
later = NOW + pd.Timedelta(hours=1)
check("고른 끝이 지금보다 늦으면 지금까지만", data._span(H2, later, NOW), (later - H2, NOW))
check("시간 폴더: 정각에 끝나면 그 시간 폴더는 읽지 않음, 빈 구간은 아무 폴더도",
      (data._hour_partitions(END - H2, END), data._hour_partitions(NOW, NOW)),
      ("(dt = '2026-10-23' AND hour = '04') OR (dt = '2026-10-23' AND hour = '05')", "FALSE"))

# --- 날짜 지정 SQL ---
s, lag = sql_of(data._real_bronze_lag, LAG_COLS, 120, END)
check("지연: 고른 구간의 시간 폴더(04·05시)와 시작·끝 조건",
      ("(dt = '2026-10-23' AND hour = '04')" in s, "(dt = '2026-10-23' AND hour = '05')" in s,
       "hour = '03'" in s, "hour = '06'" in s,
       "collected_at >= TIMESTAMP '2026-10-23 04:00:00'" in s, "collected_at < TIMESTAMP '2026-10-23 06:00:00'" in s),
      (True, True, False, False, True, True))
check("지연: 결과가 비어도 칸 이름은 화면 규칙(partition)", "partition" in lag.columns, True)
s, _ = sql_of(data._real_topic_inflow, INFLOW_COLS, 120, END)
check("유입: 고른 구간 그대로 (덜 찬 분 빼기는 지금 근처에서만)",
      ("kafka_timestamp >= TIMESTAMP '2026-10-23 04:00:00'" in s, "kafka_timestamp < TIMESTAMP '2026-10-23 06:00:00'" in s,
       "hour = '06'" in s), (True, True, False))
s, _ = sql_of(data._real_topic_inflow, INFLOW_COLS, 120, later)
check("유입: 끝이 지금보다 늦으면 덜 찬 분을 뺀 끝(05:29)에서 자름",
      ("kafka_timestamp >= TIMESTAMP '2026-10-24 04:30:20'" in s, "kafka_timestamp < TIMESTAMP '2026-10-24 05:29:00'" in s),
      (True, True))
s, _ = sql_of(data._real_payment_attempts, ATTEMPT_COLS, 2, END)
check("결제: completed_at 이 고른 구간 안",
      ("completed_at >= TIMESTAMP '2026-10-23 04:00:00'" in s, "completed_at < TIMESTAMP '2026-10-23 06:00:00'" in s),
      (True, True))
s, _ = sql_of(data._real_duplicate_success, DUP_COLS, 2, END)
check("성공 결제 중복: 고른 구간에 적재된 성공 결제",
      ("loaded_at >= TIMESTAMP '2026-10-23 04:00:00'" in s, "loaded_at < TIMESTAMP '2026-10-23 06:00:00'" in s),
      (True, True))
s, _ = sql_of(data._real_malformed_events, MALFORMED_COLS, 2, END)
check("형식 오류: 시간 폴더 04·05시, kafka_timestamp 가 고른 구간 안",
      ("(dt = '2026-10-23' AND hour = '04')" in s, "hour = '06'" in s,
       "kafka_timestamp >= TIMESTAMP '2026-10-23 04:00:00'" in s, "kafka_timestamp < TIMESTAMP '2026-10-23 06:00:00'" in s),
      (True, False, True, True))


# --- 신뢰성 점검 (날짜 지정) ---
class FakeRow:
    """신뢰성 점검 조회처럼 한 줄을 돌려준다."""

    def __init__(self, **changes):
        self.row, self.sql = {**REL, **changes}, []

    def __call__(self, sql):
        self.sql.append(sql)
        return pd.DataFrame([[None if v is None else str(v) for v in self.row.values()]], columns=list(self.row))


def past_checks(**changes):
    q = FakeRow(**changes)
    return data._real_reliability_checks(120, END, query=q, now=NOW).set_index("check"), q.sql[0]


r, s = past_checks()
check("신뢰성 점검(날짜 지정): Kafka 시각 04:00~06:00, 지연 수집기 측정 간격의 끝점도 04:00·06:00",
      ("kafka_timestamp >= TIMESTAMP '2026-10-23 04:00:00'" in s, "kafka_timestamp < TIMESTAMP '2026-10-23 06:00:00'" in s,
       "UNION ALL SELECT TIMESTAMP '2026-10-23 04:00:00' UNION ALL SELECT TIMESTAMP '2026-10-23 06:00:00'" in s,
       "hour = '06'" in s), (True, True, True, False))
check("신뢰성 점검(날짜 지정): 정상이면 '구간'으로 적고 지금 기준 마지막 기록은 적지 않음",
      (list(r.result), r.detail[GAP], r.detail[STALL]),
      (["정상"] * 3, "구간 빈틈 0건 (파티션 15개)", "가장 늦게 쓴 메시지 68초 · 지연 수집기 측정 간격 최대 60초"))
r, _ = past_checks(load_late_sec=900, load_late_at="2026-10-23 04:17:00.000")
check("신뢰성 점검(날짜 지정): 그때 2분 넘게 늦게 쓴 메시지가 있으면 문제",
      (r.result[STALL], r.detail[STALL]), ("문제", "적재 잡이 10-23 13:17 KST 메시지를 15분 늦게 씀"))
r, _ = past_checks(collect_gap_sec=600, collect_gap_end="2026-10-23 06:00:00.000")
check("신뢰성 점검(날짜 지정): 구간 끝까지 빈 측정도 측정 간격으로 적음 (지금 기준이 아님)",
      (r.result[STALL], r.detail[STALL]), ("문제", "지연 수집기 측정 간격 10분 (10-23 14:50~15:00 KST)"))
r, _ = past_checks(load_late_sec=None, load_late_at=None, last_loaded=None, partitions_seen=0)
check("신뢰성 점검(날짜 지정): 그 구간에 원장 기록이 없으면 빈틈은 확인 필요, 적재 정지는 문제",
      (r.result[GAP], r.result[STALL], r.detail[STALL]), ("확인 필요", "문제", "적재 잡 구간 기록 없음"))

# --- 비면 더미? 실시간은 지금처럼 더미, 날짜 지정은 빈 표 그대로 ---
empty_lag = data.get_bronze_lag.__wrapped__(3).iloc[0:0]
empty_pay = data.get_payment_attempts.__wrapped__(1).iloc[0:0]
data._REAL.clear()
data._REAL.update({"get_bronze_lag": lambda minutes=180, end=None: empty_lag,
                   "get_payment_attempts": lambda hours=6, end=None: empty_pay})
data.USING_DUMMY.clear()
st.cache_data.clear()
check("빈 실데이터(실시간): 지연·결제는 지금처럼 더미로 대체",
      (len(data.get_bronze_lag(180)) > 0, len(data.get_payment_attempts(3)) > 0, sorted(data.USING_DUMMY)),
      (True, True, ["get_bronze_lag", "get_payment_attempts"]))
data.USING_DUMMY.clear()
check("빈 실데이터(날짜 지정): 더미로 바꾸지 않고 빈 표 그대로 ('그때 기록 없음')",
      (len(data.get_bronze_lag(120, END)), len(data.get_payment_attempts(2, END)), sorted(data.USING_DUMMY)),
      (0, 0, []))
data._REAL.clear()
data.USING_DUMMY.clear()

# --- 더미도 고른 구간 안에서 만든다 (Athena 없이 볼 때) ---
d = data.get_bronze_lag.__wrapped__(120, END)
check("더미 지연: 고른 구간 안, 1분마다", (d.collected_at.min() >= END - H2, d.collected_at.max() < END,
                                  d.collected_at.nunique()), (True, True, 120))
d = data.get_topic_inflow.__wrapped__(120, END)
check("더미 유입: 고른 구간 안", (d.minute.min() >= END - H2, d.minute.max() < END), (True, True))
d = data.get_payment_attempts.__wrapped__(2, END)
check("더미 결제: 고른 구간 안", (d.completed_at.min() > END - H2, d.completed_at.max() <= END), (True, True))
d = data.get_malformed_events.__wrapped__(2, END)
check("더미 형식 오류: 고른 구간 안", (d.kafka_timestamp.min() > END - H2, d.kafka_timestamp.max() <= END), (True, True))

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
    kst_now = pd.Timestamp.now(tz="Asia/Seoul")
    yesterday = (kst_now - pd.Timedelta(days=1)).date()
    midnight = pd.Timestamp(yesterday).tz_localize("Asia/Seoul")
    y15 = (midnight + pd.Timedelta(hours=15)).tz_convert("UTC")
    y14 = (midnight + pd.Timedelta(hours=14)).tz_convert("UTC")
    label = f"{yesterday:%m-%d} 13:00~15:00 KST"
    calls = []

    def rec(name, make):
        def fn(*args, **kwargs):
            calls.append((name, args))
            return make(*args, **kwargs)
        return fn

    def texts(elements):
        return [str(e.value) for e in elements]

    def open_page(path, registered):
        data._REAL.clear()
        data._REAL.update(registered)
        data.USING_DUMMY.clear()
        st.cache_data.clear()
        calls.clear()
        return AppTest.from_file(path, default_timeout=30).run()

    def pick_day(at, key, hours=(13, 15), day=None):
        at = at.radio(key=f"win_{key}").set_value("날짜 지정").run()
        at.date_input(key=f"win_{key}_day").set_value(day or yesterday)
        calls.clear()
        return at.slider(key=f"win_{key}_range").set_value(hours).run()

    def called(name):
        return [args for n, args in calls if n == name]

    pipeline = {
        "get_bronze_lag": rec("lag", lambda minutes=180, end=None: data.get_bronze_lag.__wrapped__(minutes, end)),
        "get_topic_inflow": rec("inflow", lambda minutes=180, end=None: data.get_topic_inflow.__wrapped__(minutes, end)),
        "get_reliability_checks": rec("rel", lambda minutes=180, end=None: data._real_reliability_checks(
            minutes, end, query=FakeRow(), now=NOW)),
    }
    at = open_page("pages_data/pipeline.py", pipeline)
    check("파이프라인 상태(기본 최근 3시간): 오류 없이 열림, 조회 함수는 끝 없이(지금까지)",
          (texts(at.exception), called("lag"), called("inflow"), called("rel")),
          ([], [(180, None)], [(180, None)], [(180, None)]))
    at = pick_day(at, "pipeline")
    md = texts(at.markdown)
    check("파이프라인 상태(날짜 지정): 지연·유입·점검이 모두 고른 구간(2시간, 끝 = 어제 15시 KST)으로",
          (texts(at.exception), called("lag"), called("inflow"), called("rel")),
          ([], [(120, y15)], [(120, y15)], [(120, y15)]))
    check("파이프라인 상태(날짜 지정): 카드는 구간 최대·측정한 분, 점검 칸 부제에 고른 구간",
          (any("구간 최대" in m for m in md), any("측정한 분" in m for m in md), any(label in m for m in md),
           any(c.startswith("구간 마지막 1분 건수") for c in texts(at.caption))),
          (True, True, True, True))
    check("파이프라인 상태(날짜 지정): 화면이 고른 시각을 기억함 (다시 그려도 같은 구간)",
          (at.radio(key="win_pipeline").value, at.slider(key="win_pipeline_range").value), ("날짜 지정", (13, 15)))
    empty = {**pipeline, "get_bronze_lag": rec("lag", lambda minutes=180, end=None: empty_lag)}
    at = pick_day(open_page("pages_data/pipeline.py", empty), "pipeline")
    check("파이프라인 상태(날짜 지정, 지연 기록 없음): 더미 대신 '기록 없음', 아래 칸은 그대로",
          (texts(at.exception), any("지연 측정 기록이 없습니다" in i and label in i for i in texts(at.info)),
           any(c.startswith("※ 지금 더미 데이터") for c in texts(at.caption)), called("rel")),
          ([], True, False, [(120, y15)]))

    payments = {
        "get_payment_attempts": rec("pay", lambda hours=6, end=None: data.get_payment_attempts.__wrapped__(hours, end)),
        "get_duplicate_success": rec("dup", lambda hours=6, end=None: data._real_duplicate_success(
            hours, end, query=FakeAthena(DUP_COLS, []), now=NOW)),
    }
    at = open_page("pages_data/payments.py", payments)
    check("결제 관제(기본 최근 3시간): 결제·성공 결제 중복이 같은 구간(끝 없음)",
          (texts(at.exception), called("pay"), called("dup")), ([], [(3, None)], [(3, None)]))
    at = pick_day(at, "payments")
    md = texts(at.markdown)
    check("결제 관제(날짜 지정): 결제·성공 결제 중복이 고른 구간으로, 카드·칸 부제에 고른 구간",
          (texts(at.exception), called("pay"), called("dup"), any(label in m for m in md),
           any(f"시나리오 3 · {label} 적재 기준" in m for m in md)),
          ([], [(2, y15)], [(2, y15)], True, True))
    empty = {**payments, "get_payment_attempts": rec("pay", lambda hours=6, end=None: empty_pay)}
    at = pick_day(open_page("pages_data/payments.py", empty), "payments")
    check("결제 관제(날짜 지정, 결제 없음): 더미 대신 '결제가 없습니다', 더미 안내 없음",
          (texts(at.exception), texts(at.info), any(c.startswith("※ 현재는 더미") for c in texts(at.caption))),
          ([], [f"{label}에 결제가 없습니다."], False))

    malformed_rows = [("payments", 1, 204, (y14 - pd.Timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S.000"),
                       "pg", "INVALID_VALUE", "0.2.0")]
    for rows, want in (([], f"{label} 동안 형식 오류가 없습니다 (0건)."), (malformed_rows, f"{label}의 형식 오류입니다.")):
        malformed = {"get_malformed_events": rec("mal", lambda hours=6, end=None, rows=rows: data._real_malformed_events(
            hours, end, query=FakeAthena(MALFORMED_COLS, rows), now=NOW))}
        at = open_page("pages_data/malformed.py", malformed)
        first = called("mal")
        at = pick_day(at, "malformed")
        check(f"형식 오류(날짜 지정, {len(rows)}건): 기본은 최근 6시간, 고르면 그 구간으로, 문구에 고른 구간",
              (texts(at.exception), first, called("mal"), want in texts(at.success) + texts(at.caption)),
              ([], [(6, None)], [(2, y15)], True))
    at = pick_day(open_page("pages_data/malformed.py", malformed), "malformed", hours=(13, 13))
    check("같은 시각을 고르면 그 시각부터 한 시간", called("mal"), [(1, y14)])

    if kst_now.hour < 23:
        at = pick_day(open_page("pages_data/malformed.py", malformed), "malformed", hours=(23, 24), day=kst_now.date())
        check("아직 오지 않은 시간을 고르면 안내만 하고 조회하지 않음",
              (texts(at.exception), any("아직 오지 않은 시간" in i for i in texts(at.info)), called("mal")), ([], True, []))
    else:
        print("건너뜀 아직 오지 않은 시간 시험: 지금이 23시 이후(KST)")
    data._REAL.clear()

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
