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
check("정답표 3건을 읽음", [i["incident_id"] for i in inc], ["INC-001", "INC-002", "INC-003"])
check("탐지: PG 장애·소비 지연은 OK, 스키마 오염은 LATE", [d["status"] for d in res["detection"]], ["OK", "OK", "LATE"])
check("탐지 지연(분): 10, 10, 14", [d["delay_min"] for d in res["detection"]], [10.0, 10.0, 14.0])
check("적발 수는 허용 지연 안에 잡은 것만 2/3", (res["detected"], res["total"]), (2, 3))
check("오탐: PG_B 2건은 이어져서 1덩어리", res["false_alarms"], {"count": 2, "episodes": 1})
check("층 판별: 스키마 오염을 INGEST로 잘못 말함", [x["status"] for x in res["layer"]], ["OK", "OK", "WRONG"])
check("근거 연결: 주장 6개 중 4개", (res["evidence"]["claims"], res["evidence"]["backed"], res["evidence"]["ratio"]), (6, 4, 0.667))

# --- 재처리 뒤 다시 판정한 줄은 채점에서 빠진다 ---
check("순찰 기록이 있으면 REDETECT 줄 제외", len(regular_rows(anoms, runs)), 6)
check("순찰 기록이 없어도 run_id의 -RD- 로 제외", len(regular_rows(anoms)), 6)

# --- 허용 지연을 바꾸면 결과가 바뀐다 ---
res2 = score(inc, anoms, runs, None, allow={"SCHEMA_POLLUTION": 15})
check("스키마 오염 허용을 15분으로 늘리면 3/3", (res2["detected"], res2["total"]), (3, 3))
check("리포트가 없으면 층·근거는 채점 안 함", "layer" in res2, False)

# --- 직접 만든 경우들 ---
def anomaly(aid, atype, st, sk, det, ws=None):
    return {"run_id": "r-" + aid, "anomaly_id": aid, "anomaly_type": atype, "scope_type": st, "scope_key": sk,
            "window_start": ws or det, "window_end": det, "detected_at": det}

one = [dict(inc[0])]
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 15:10:00")])
check("대상이 다르면(PG_B) 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 14:50:00")])
check("장애 시작 전에 울린 것은 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(one, [anomaly("x", "MALFORMED_SPIKE", "pg", "PG_A", "2026-10-20 15:10:00")])
check("종류가 다른 이상은 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:00:00")])
check("시작과 같은 시각은 0분 만에 잡음", (det[0]["status"], det[0]["delay_min"]), ("OK", 0.0))
det, _ = score_detection(one, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:50:00")])
check("종료 후 허용 시간 밖(15:50)은 못 잡은 것", det[0]["status"], "MISSED")
star = [dict(inc[1], scope_key="*")]
det, _ = score_detection(star, [anomaly("y", "BRONZE_LAG_SPIKE", "topic", "payments", "2026-10-20 16:05:00")])
check("대상이 *이면 어느 토픽이든 인정", det[0]["status"], "OK")
check("시각에 Z·+09:00이 붙어도 UTC로 맞춤", (parse_time("2026-10-20T15:00:00Z"), parse_time("2026-10-21T00:00:00+09:00")),
      (parse_time("2026-10-20 15:00:00"), parse_time("2026-10-20 15:00:00")))
far = [anomaly("f1", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 10:00:00"), anomaly("f2", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 10:30:00"),
       anomaly("f3", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 11:00:00")]
check("오탐 3건이 15분 안 간격이 아니면 3덩어리", score([inc[0]], far)["false_alarms"], {"count": 3, "episodes": 3})

# --- 정답표를 폴더가 아니라 파일 하나(목록)로 줘도 읽음, 시험용 폴더로 확인 ---
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "all.json")
    json.dump(inc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    check("정답표 파일 하나(목록)도 읽음", len(load_incidents(path)), 3)
    bad = os.path.join(d, "bad.json")
    json.dump({**inc[0], "scenario": "MYSTERY"}, open(bad, "w"))
    try:
        load_incidents(bad)
        check("모르는 사건 종류는 오류", "통과됨", "오류")
    except ValueError:
        check("모르는 사건 종류는 오류", "오류", "오류")
check("사건 종류 3개 정의", sorted(SCENARIOS), ["INGEST_LAG", "PG_OUTAGE", "SCHEMA_POLLUTION"])
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
