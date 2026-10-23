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
check("한도까지 못 고친 리포트는 원인 층 UNKNOWN, 결론 앞에 검증 미통과와 모델이 낸 층을 표시", (r["cause_layer"], r["conclusion"].startswith("[검증 미통과 · 모델이 낸 원인 층: PAYMENT]")), ("UNKNOWN", True))
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

# --- 재영 님 리뷰: 조회와 제출을 한 응답에 같이 요청하면 제출은 받지 않는다 ---
conv, calls = script([use(1, "payment_summary", **W), use(2, "submit_report", **REPORT)], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("조회와 같은 응답에서 낸 제출은 거절하고, 조회 결과를 받은 다음 응답의 제출만 받음", ([t["status"] for t in r["trace"]], "problems" in r, len(calls)), (["ok", "rejected"], False, 2))
check("거절 이유와 조회 결과가 함께 모델에 전달됨", ("다음 응답" in str(calls[1]["messages"][-1]), "toolResult" in str(calls[1]["messages"][-1])), (True, True))
conv, calls = script(*[[use(i, "payment_summary", **W), use(i + 100, "submit_report", **REPORT)] for i in range(5)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW, max_turns=4, max_revisions=0)
check("같은 응답 제출을 계속 반복하면 되돌림 한도가 0이어도 받지 않고 UNKNOWN 리포트", (r["cause_layer"], len([t for t in r["trace"] if t["status"] == "rejected"])), ("UNKNOWN", 4))
conv, calls = script([use(1, "submit_report", **REPORT)], [use(2, "payment_summary", **W)], [use(3, "submit_report", **REPORT)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("조회 없이 먼저 낸 제출은 부르지 않은 도구를 근거로 댔으니 거절 (다음 응답에서 조회 뒤 통과)", [t["status"] for t in r["trace"]], ["rejected", "ok"])
# --- 확인하지 않은 것을 "없다/정상"이라고 단정하는 문장 (결론·사실 문장 검사) ---
from report import check_report, unsupported_denials

check("단정 검사: 중복 확인 도구 없이 '오염이 없다'고 쓰면 걸림", [x[2] for x in unsupported_denials("PG_A 장애입니다. 원본 데이터에 오염이 없습니다.", {"payment_summary"})], ["데이터 오염·중복"])
check("단정 검사: 도구를 부른 뒤에는 통과", unsupported_denials("원본 데이터에 오염이 없습니다.", {"duplicate_success_orders"}), [])
check("단정 검사: 형식 오류는 malformed_summary나 malformed_fields 중 하나면 통과", (len(unsupported_denials("형식 오류도 없습니다.", set())), len(unsupported_denials("형식 오류도 없습니다.", {"malformed_fields"}))), (1, 0))
check("단정 검사: 원장이 정상이라는 말은 ledger_reliability가 필요", (len(unsupported_denials("원장 적재는 정상입니다.", {"payment_summary"})), len(unsupported_denials("원장 적재는 정상입니다.", {"ledger_reliability"}))), (1, 0))
check("단정 검사: 불확실성을 밝힌 문장('확인할 수 없습니다', '확인하지 못했습니다')은 걸리지 않음",
      [unsupported_denials(t, set()) for t in ("중복 여부를 확인할 수 없습니다.", "형식 오류는 확인하지 못했습니다.", "지연은 알 수 없고 불확실합니다.")], [[], [], []])
check("단정 검사: 불확실 문장이 섞여도 단정 부분(오염 없음)은 걸림", "데이터 오염·중복" in [x[2] for x in unsupported_denials("원장은 확인할 수 없지만 오염은 없습니다.", set())], True)
check("단정 검사: '있다'는 문장(중복 3건이 있음)은 걸리지 않음", unsupported_denials("성공 결제가 중복된 주문이 3개 있습니다.", set()), [])
check("단정 검사: 낱말이 없는 문장(PG 원인 실패 0건)은 걸리지 않음", unsupported_denials("PG_B의 PG 원인 실패는 0건입니다.", set()), [])
problems = check_report(dict(REPORT, conclusion="PG_A 장애입니다. 데이터 오염은 없습니다."), {"payment_summary"})
check("리포트 검사: 결론에 근거 없는 '오염 없음'이 있으면 고쳐야 할 점이 나옴", (len(problems), "duplicate_success_orders" in problems[0]), (1, True))
check("리포트 검사: 추정(ASSUMPTION) 문장의 '없을 것'은 보지 않음",
      check_report(dict(REPORT, claims=REPORT["claims"] + [{"text": "오염은 없을 것으로 보입니다", "kind": "ASSUMPTION", "evidence": []}]), {"payment_summary"}), [])
check("리포트 검사: 사실(FACT) 문장의 근거 없는 단정도 걸림",
      len(check_report(dict(REPORT, claims=[{"text": "형식 오류는 없습니다", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]}]), {"payment_summary"})), 1)

# 루프 한 바퀴: 처음엔 단정 때문에 되돌려지고, 도구를 부른 뒤 다시 내면 받아들여짐
unsup = dict(REPORT, conclusion="PG_A 장애입니다. 원본 데이터에 오염이 없습니다.")
fixed = dict(REPORT, conclusion="PG_A 장애입니다. 같은 시간대 성공 결제 중복도 확인했고 없습니다.")
conv, calls = script([use(1, "payment_summary", **W)], [use(2, "submit_report", **unsup)],
                     [use(3, "duplicate_success_orders", **W)], [use(4, "submit_report", **fixed)])
r = investigate(PG_ANOMALY, conv, execute, dialect="sqlite", now=NOW)
check("단정 때문에 되돌려지고, 확인 도구를 부른 뒤 다시 내면 받아들여짐", ([t["status"] for t in r["trace"]], "problems" in r), (["ok", "rejected", "ok"], False))
check("되돌림 이유에 필요한 도구 이름이 들어 있음", "duplicate_success_orders" in str(calls[2]["messages"][-1]), True)

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
