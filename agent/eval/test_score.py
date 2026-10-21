"""채점 스크립트 시험. 예시 파일(sample/)과 직접 만든 경우들로 점수가 맞게 나오는지 본다.

실행: python3 test_score.py
"""
import json
import os
import tempfile

from score import SCENARIOS, load_incidents, load_rows, parse_time, regular_rows, score, score_detection

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, "sample")
ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


inc = load_incidents(os.path.join(S, "incident_log"))
anoms, runs = load_rows(os.path.join(S, "anomalies.json")), load_rows(os.path.join(S, "detection_runs.json"))
reports = json.load(open(os.path.join(S, "reports.json"), encoding="utf-8"))

# --- 예시 파일로 전체 점수 ---
res = score(inc, anoms, runs, reports)
check("정답표 start·end 쌍 5건을 읽음", [i["incident_id"] for i in inc], ["inc-surge", "inc-pg", "inc-lag", "inc-dup", "inc-total"])
check("시작·끝 시각을 UTC로 짝지음", (inc[1]["injected_start"], inc[1]["injected_end"], inc[1]["ended_by"]),
      (parse_time("2026-10-20 15:00:00"), parse_time("2026-10-20 15:10:00"), "timer"))
check("PG 장애의 대상은 params.pg에서", inc[1]["scope"], ("pg", "PG_A"))
check("오염은 params.kind로 기준을 고름", [i["scenario"] for i in inc], [None, "PG_OUTAGE", "INGEST_LAG", "DUPLICATE_SUCCESS_PAYMENT", "ORDER_TOTAL_MISMATCH"])
check("탐지: PG 장애·소비 지연 OK, 중복 성공 결제 LATE, 주문 총액은 규칙 없음", [d["status"] for d in res["detection"]], ["OK", "OK", "LATE", "NO_RULE"])
check("탐지 지연(분): 10, 10, 14", [d["delay_min"] for d in res["detection"]][:3], [10.0, 10.0, 14.0])
check("적발 2/3 (규칙 없는 사건은 분모에서 뺌), 규칙 없음 1, 채점 대상 아님 1", (res["detected"], res["total"], res["no_rule"], res["not_scored"]), (2, 3, 1, 1))
check("오탐: 약한 급증(12시) 구간의 PG_B 2건은 이어져서 1덩어리", res["false_alarms"], {"count": 2, "episodes": 1})
check("층 판별: 중복 성공 결제를 INGEST로 잘못 말함", [x["status"] for x in res["layer"]], ["OK", "OK", "WRONG"])
check("근거 연결: 주장 6개 중 4개", (res["evidence"]["claims"], res["evidence"]["backed"], res["evidence"]["ratio"]), (6, 4, 0.667))

# --- 재처리 뒤 다시 판정한 줄은 채점에서 빠진다 ---
check("순찰 기록이 있으면 REDETECT 줄 제외", len(regular_rows(anoms, runs)), 6)
check("순찰 기록이 없어도 run_id의 -RD- 로 제외", len(regular_rows(anoms)), 6)

# --- 허용 지연을 바꾸면 결과가 바뀐다 ---
res2 = score(inc, anoms, runs, None, allow={"DUPLICATE_SUCCESS_PAYMENT": 15})
check("중복 성공 결제 허용을 15분으로 늘리면 3/3", (res2["detected"], res2["total"]), (3, 3))
check("리포트가 없으면 층·근거는 채점 안 함", "layer" in res2, False)

# --- 직접 만든 경우들 ---
def anomaly(aid, atype, st, sk, det, ws=None):
    return {"run_id": "r-" + aid, "anomaly_id": aid, "anomaly_type": atype, "scope_type": st, "scope_key": sk,
            "window_start": ws or det, "window_end": det, "detected_at": det}

one = [dict(inc[1])]
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 15:10:00")])
check("대상이 다르면(PG_B) 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 14:50:00")])
check("장애 시작 전에 울린 것은 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(one, [anomaly("x", "MALFORMED_SPIKE", "pg", "PG_A", "2026-10-20 15:10:00")])
check("종류가 다른 이상은 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:00:00")])
check("시작과 같은 시각은 0분 만에 잡음", (det[0]["status"], det[0]["delay_min"]), ("OK", 0.0))
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:50:00")])
check("종료 후 허용 지연의 2배(15:40)를 넘긴 것(15:50)은 못 잡은 것", det[0]["status"], "MISSED")
star = [dict(inc[2])]
det, _ = score_detection(star, [anomaly("y", "BRONZE_LAG_SPIKE", "topic", "payments", "2026-10-20 16:05:00")])
check("소비 지연은 어느 토픽이든 인정", det[0]["status"], "OK")
check("시각에 Z·+09:00이 붙어도 UTC로 맞춤", (parse_time("2026-10-20T15:00:00Z"), parse_time("2026-10-21T00:00:00+09:00")),
      (parse_time("2026-10-20 15:00:00"), parse_time("2026-10-20 15:00:00")))
far = [anomaly("f1", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 10:00:00"), anomaly("f2", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 10:30:00"),
       anomaly("f3", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 11:00:00")]
check("오탐 3건이 15분 안 간격이 아니면 3덩어리", score([inc[1]], far)["false_alarms"], {"count": 3, "episodes": 3})

# --- 정답표 읽기: 폴더 대신 파일 하나(목록), 끝 기록 없음, 적용 실패, 모르는 종류 ---
def rec(iid, phase, typ, at, **extra):
    return {"schema_version": 1, "incident_id": iid, "phase": phase, "type": typ, "at": at, **extra}


with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "all.json")
    json.dump([rec("a", "start", "PG_OUTAGE", "2026-10-20T15:00:00Z", params={"pg": "PG_B", "planned_minutes": 10}),
               rec("a", "end", "PG_OUTAGE", "2026-10-20T15:10:00Z", ended_by="manual", result={})], open(path, "w", encoding="utf-8"))
    got = load_incidents(path)
    check("정답표 파일 하나(목록)도 읽음", (len(got), got[0]["ended_by"], got[0]["scope"]), (1, "manual", ("pg", "PG_B")))
    json.dump([rec("b", "start", "INGEST_LAG", "2026-10-20T16:00:00Z", params={"mode": "burst", "planned_minutes": 15})], open(path, "w"))
    got = load_incidents(path)
    check("끝 기록이 없으면 계획한 시간(15분)만큼 이어졌다고 봄", (got[0]["injected_end"], got[0]["ended_by"]), (parse_time("2026-10-20 16:15:00"), None))
    json.dump([rec("c", "start", "PG_OUTAGE", "2026-10-20T17:00:00Z", params={"pg": "PG_A", "planned_minutes": 10}),
               rec("c", "end", "PG_OUTAGE", "2026-10-20T17:00:00Z", ended_by="failed", result={})], open(path, "w"))
    check("적용에 실패한 사건은 채점하지 않음", load_incidents(path)[0]["scenario"], None)
    json.dump([rec("p", "start", "OPERATOR_PAUSE", "2026-10-20T18:00:00Z", params={})], open(path, "w"))
    check("일시 정지는 채점 대상이 아님", load_incidents(path)[0]["scenario"], None)
    json.dump([rec("d", "start", "DATA_POLLUTION", "2026-10-20T18:00:00Z", params={"kind": "MYSTERY"})], open(path, "w"))
    try:
        load_incidents(path)
        check("모르는 오염 종류는 오류", "통과됨", "오류")
    except ValueError:
        check("모르는 오염 종류는 오류", "오류", "오류")
check("채점하는 종류 4개 정의", sorted(SCENARIOS), ["DUPLICATE_SUCCESS_PAYMENT", "INGEST_LAG", "ORDER_TOTAL_MISMATCH", "PG_OUTAGE"])
# --- 추정(ASSUMPTION)은 근거 연결 점수에서 뺀다 ---
rep_a = [{"anomaly_id": "a-r1-1", "cause_layer": "PAYMENT", "claims": [
    {"text": "사실", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]},
    {"text": "근거 없는 사실", "kind": "FACT", "evidence": []},
    {"text": "추정", "kind": "ASSUMPTION", "evidence": []}]}]
res3 = score(inc, anoms, runs, rep_a)
check("근거 연결: 사실 2개 중 1개만 근거 있음, 추정은 세지 않음", (res3["evidence"]["claims"], res3["evidence"]["backed"]), (2, 1))
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
