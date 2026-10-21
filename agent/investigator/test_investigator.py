"""조사 루프 시험. 가짜 모델(정해 둔 순서대로 도구를 부름)과 가짜 원장으로 루프의 배관이 맞는지 본다.

이 시험이 확인하는 것: 도구 호출 → 결과 전달 → 리포트 검사 → 제출의 흐름, 울타리·검사에 걸렸을 때의 처리.
이 시험이 확인하지 못하는 것: 진짜 모델이 도구를 잘 고르고 원인을 잘 맞히는지 (Bedrock 연결 뒤에 정답표로 채점해야 한다).

실행: python3 test_investigator.py
"""
from datetime import datetime

from loop import investigate
from report import SUBMIT_REPORT_SPEC

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


NOW = datetime(2026, 10, 20, 15, 30, 0)
W = {"window_start": "2026-10-20T15:00:00", "window_end": "2026-10-20T15:30:00"}


def execute(sql):
    """가짜 원장: 표 이름만 보고 정해진 줄을 돌려준다 (SQL 내용은 울타리 시험이 따로 본다)."""
    if "payment_attempts" in sql:
        return [{"pg": "PG_A", "attempts": 40, "pg_cause_failures": 30}]
    if "bronze_lag_snapshots" in sql:
        return [{"topic": "orders", "max_lag_sec": 200.0}]
    return []


def use(i, name, **args):
    return {"toolUse": {"toolUseId": f"t{i}", "name": name, "input": args}}


def script(*turns):
    """turn 하나 = 모델이 한 번에 내는 블록 목록. 순서대로 돌려주고, 받은 메시지는 calls에 기록한다."""
    it, calls = iter(turns), []

    def converse(system, messages, tool_specs):
        calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": [s["toolSpec"]["name"] for s in tool_specs]})
        return {"role": "assistant", "content": next(it)}
    return converse, calls


REPORT = dict(cause_layer="PAYMENT", conclusion="PG_A 장애입니다. 재처리는 필요 없습니다.",
              claims=[{"text": "PG_A의 PG 원인 실패 30건", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]}])
PG_ANOMALY = {"anomaly_id": "a-1", "anomaly_type": "PG_FAILURE_SPIKE", "scope_type": "pg", "scope_key": "PG_A", "ground_truth": "정답"}

# --- 정상 흐름 ---
conv, calls = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("정상: 리포트가 이상 번호와 원인 층을 가짐", (r["anomaly_id"], r["cause_layer"]), ("a-1", "PAYMENT"))
check("정상: 문제 없음(problems 없음), 주장 1개", ("problems" in r, len(r["claims"])), (False, 1))
check("정상: 조사 기록에 도구 호출이 남음", [t["tool"] for t in r["trace"]], ["payment_summary"])
check("정상: 모델에 도구 12개(조회 11 + 제출 1)를 알려 줌", len(calls[0]["tools"]), 12)
check("정상: 도구 결과가 다음 메시지로 모델에 전달됨", "toolResult" in calls[1]["messages"][-1]["content"][0], True)
check("정상: 정답 관련 값(ground_truth)은 모델에 보내지 않음", "ground_truth" in str(calls[0]["messages"][0]) or "정답" in str(calls[0]["messages"][0]), False)
check("정상: 지시문에 원칙(읽기만, 근거 필수)이 들어 있음", "submit_report" in calls[0]["system"] and "읽기만" in calls[0]["system"], True)

# --- 리포트 검사 ---
bad = dict(REPORT, claims=[{"text": "측정값", "kind": "FACT", "evidence": [{"tool": "bronze_lag"}]}])      # 부르지 않은 도구를 근거로 댐
conv, calls = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **bad)], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("부르지 않은 도구를 근거로 대면 거절하고 다시 쓰게 함", ([t["status"] for t in r["trace"]], "problems" in r), (["ok", "rejected"], False))
check("거절 이유가 모델에 전달됨", "bronze_lag" in str(calls[2]["messages"][-1]), True)
conv, _ = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **dict(REPORT, claims=[{"text": "근거 없음", "kind": "FACT", "evidence": []}]))],
                 [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("근거 없는 주장은 거절", [t["status"] for t in r["trace"]], ["ok", "rejected"])
worse = dict(REPORT, claims=[{"text": "근거 없음", "kind": "FACT", "evidence": []}])
conv, _ = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **worse)], [use(3, "submit_report", **worse)], [use(4, "submit_report", **worse)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("계속 고치지 못하면 2번 거절한 뒤 받되 problems를 남김(채점에서 근거 없는 주장으로 셈)", (len([t for t in r["trace"] if t["status"] == "rejected"]), len(r["problems"])), (2, 1))
conv, _ = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **dict(REPORT, cause_layer="STORAGE"))], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("모르는 원인 층은 거절", (r["trace"][1]["status"], r["cause_layer"]), ("rejected", "PAYMENT"))

# --- 울타리와 잘못된 호출 ---
conv, calls = script([use(1, "payment_summary", window_start="2026-10-20T00:00:00", window_end="2026-10-20T12:00:00")],
                     [use(2, "payment_summary", **W)], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("6시간 넘는 범위는 울타리가 막고, 모델이 범위를 줄여 다시 시도함", ([t["status"] for t in r["trace"]], r["cause_layer"]), (["error", "ok"], "PAYMENT"))
check("울타리 메시지가 모델에 전달됨", "6시간" in str(calls[1]["messages"][-1]), True)
conv, _ = script([use(1, "delete_everything")], [use(2, "payment_summary", **W)], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("없는 도구를 부르면 오류로 돌려주고 계속함", [t["status"] for t in r["trace"]], ["error", "ok"])
conv, _ = script([use(1, "payment_summary")], [use(2, "payment_summary", **W)], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("필수 인자가 빠지면 오류로 돌려주고 계속함", [t["status"] for t in r["trace"]], ["error", "ok"])
conv, _ = script([use(1, "payment_summary", **W)], [use(2, "reprocess_request", request_id="rq-9")], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("재처리를 요청하는 도구는 존재하지 않음(읽기만)", r["trace"][1]["status"], "error")

# --- 글만 쓴 경우, 한도 ---
conv, calls = script([{"text": "아마 PG 문제일 것 같습니다."}], [use(1, "payment_summary", **W)], [use(2, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("도구 없이 글만 쓰면 제출하도록 다시 시킴", ("제출" in str(calls[1]["messages"][-1]), r["cause_layer"]), (True, "PAYMENT"))
conv, _ = script(*[[use(i, "payment_summary", **W)] for i in range(5)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW, max_turns=3)
check("한도(3회) 안에 제출 못 하면 UNKNOWN 리포트", (r["cause_layer"], len(r["trace"])), ("UNKNOWN", 3))

# --- 시나리오별 흐름: 소비 지연, 성공 결제 중복 ---
conv, _ = script([use(1, "bronze_lag", **W), use(2, "ingest_volume", **W)],
                 [use(3, "submit_report", cause_layer="INGEST", conclusion="orders 적재가 밀립니다.",
                      claims=[{"text": "orders 지연 200초", "kind": "FACT", "evidence": [{"tool": "bronze_lag"}]}, {"text": "유입 증가", "kind": "FACT", "evidence": [{"tool": "ingest_volume"}]}])])
r = investigate({"anomaly_id": "a-2", "anomaly_type": "BRONZE_LAG_SPIKE"}, conv, execute, dialect="sqlite", now=NOW)
check("소비 지연: 한 번에 도구 2개를 불러도 처리하고 INGEST 리포트", ([t["tool"] for t in r["trace"]], r["cause_layer"]), (["bronze_lag", "ingest_volume"], "INGEST"))
conv, _ = script([use(1, "duplicate_success_orders", **W)],
                 [use(2, "submit_report", cause_layer="DATA_QUALITY", conclusion="한 주문에 성공 결제가 2건입니다. 원본에 있는 오염이라 재처리해도 다시 나올 수 있습니다.",
                      claims=[{"text": "성공 결제 2건인 주문 존재", "kind": "FACT", "evidence": [{"tool": "duplicate_success_orders"}]}])])
r = investigate({"anomaly_id": "a-3", "anomaly_type": "DUPLICATE_SUCCESS_PAYMENT"}, conv, execute, dialect="sqlite", now=NOW)
check("성공 결제 중복: 새 도구를 부르고 DATA_QUALITY 리포트", ([t["tool"] for t in r["trace"]], r["cause_layer"]), (["duplicate_success_orders"], "DATA_QUALITY"))
check("제출 도구 정의에 원인 층 4가지가 들어 있음", SUBMIT_REPORT_SPEC["toolSpec"]["inputSchema"]["json"]["properties"]["cause_layer"]["enum"], ["PAYMENT", "INGEST", "DATA_QUALITY", "UNKNOWN"])

# --- 사실/추정 구분 ---
def submit(*claims, layer="PAYMENT"):
    """payment_summary를 한 번 부른 뒤 주어진 주장으로 리포트를 내는 가짜 모델로 조사한다."""
    conv, calls = script([use(1, "payment_summary", **W)], [use(2, "submit_report", cause_layer=layer, conclusion="결론", claims=list(claims))],
                         [use(3, "submit_report", **REPORT)])
    return investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW), calls


FACT_OK = {"text": "PG_A 실패 30건", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]}
GUESS = {"text": "PG_A 쪽 일시 장애일 가능성", "kind": "ASSUMPTION", "evidence": []}
r, _ = submit(FACT_OK, GUESS)
check("추정은 근거 없이도 받음 (사실 1 + 추정 1)", ([t["status"] for t in r["trace"]], [c["kind"] for c in r["claims"]], "problems" in r), (["ok"], ["FACT", "ASSUMPTION"], False))
r, _ = submit({"text": "근거 없는 사실", "kind": "FACT", "evidence": []}, GUESS)
check("근거 없는 사실(FACT)은 거절 (추정으로 바꾸라고 안내)", ([t["status"] for t in r["trace"]], "ASSUMPTION" in str(r["trace"][1])), (["ok", "rejected"], True))
r, _ = submit({"text": "kind 없음", "evidence": [{"tool": "payment_summary"}]})
check("kind가 없으면 거절", r["trace"][1]["status"], "rejected")
r, _ = submit(GUESS)
check("사실이 하나도 없이 원인 층을 고르면 거절", r["trace"][1]["status"], "rejected")
r, _ = submit(GUESS, layer="UNKNOWN")
check("증거가 부족해 UNKNOWN이면 추정만 있어도 받음", (r["cause_layer"], "problems" in r, [t["status"] for t in r["trace"]]), ("UNKNOWN", False, ["ok"]))
r, _ = submit(FACT_OK, {"text": "추정인데 안 부른 도구를 근거로", "kind": "ASSUMPTION", "evidence": [{"tool": "bronze_lag"}]})
check("추정이라도 부르지 않은 도구를 근거로 대면 거절", r["trace"][1]["status"], "rejected")
conv, calls = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **REPORT)])
investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("지시문과 제출 도구 정의에 사실/추정 구분이 들어 있음", ("ASSUMPTION" in calls[0]["system"], "ASSUMPTION" in str(SUBMIT_REPORT_SPEC)), (True, True))
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
