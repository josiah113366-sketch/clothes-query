"""채점 스크립트 시험. 실제 정답표 형식(start·end 기록 파일)의 예시(sample/)와 직접 만든 경우들로 점수가 맞게 나오는지 본다.

실행: python3 test_score.py
"""
import json
import os
import subprocess
import sys

from score import (DEFAULT_EXCLUDE_FILE, SCENARIOS, load_excluded, load_incidents, load_rows, regular_rows, score,
                   score_detection, split_incidents)

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
excluded = load_excluded(os.path.join(S, "excluded_incidents.txt"))

# --- 정답표 읽기 ---
check("start·end 파일 12개를 사건 6건으로 합침", [i["incident_id"] for i in inc], ["INC-PG", "INC-SINK", "INC-DUP", "INC-TOTAL", "INC-BURST", "INC-TEST"])
check("데이터 오염은 kind까지 붙은 이름으로", [i["key"] for i in inc], ["PG_OUTAGE", "SINK_PAUSE", "DATA_POLLUTION/DUPLICATE_SUCCESS_PAYMENT",
                                                                    "DATA_POLLUTION/ORDER_TOTAL_MISMATCH", "INGEST_LAG", "PG_OUTAGE"])
check("시작·끝 시각을 UTC로 읽음", (str(inc[1]["start"]), str(inc[1]["end"]), inc[1]["ended_by"]), ("2026-10-20 16:00:00", "2026-10-20 16:35:00", "manual"))
check("순간에 끝나는 오염은 시작 = 끝", inc[2]["start"] == inc[2]["end"], True)

# --- 채점할 것과 안 할 것 ---
graded, skipped = split_incidents(inc, excluded)
check("채점 대상은 PG 장애·Sink 정지·성공 결제 중복 3건", [i["incident_id"] for i in graded], ["INC-PG", "INC-SINK", "INC-DUP"])
check("안 하는 것: 주문 총액(기본 끔), burst, 제외 목록", [i["incident_id"] for i, _ in skipped], ["INC-TOTAL", "INC-BURST", "INC-TEST"])
check("--include로 주문 총액을 켜면 채점 대상", [i["incident_id"] for i in split_incidents(inc, excluded, {"ORDER_TOTAL_MISMATCH"})[0]],
      ["INC-PG", "INC-SINK", "INC-DUP", "INC-TOTAL"])

# --- 예시 파일로 전체 점수 ---
res = score(inc, anoms, runs, reports, excluded=excluded)
check("탐지: PG 장애·Sink 정지는 OK, 성공 결제 중복은 LATE", [d["status"] for d in res["detection"]], ["OK", "OK", "LATE"])
check("탐지 지연(분): 10, 24, 14", [d["delay_min"] for d in res["detection"]], [10.0, 24.0, 14.0])
check("허용 지연(분): 15, 30, 10", [d["allow_min"] for d in res["detection"]], [15.0, 30.0, 10.0])
check("적발 수는 허용 지연 안에 잡은 것만 2/3", (res["detected"], res["total"]), (2, 3))
check("오탐: PG_B 2건은 이어져서 1덩어리 (시험·burst·주문 총액 시간대의 이상은 안 셈)", res["false_alarms"], {"count": 2, "episodes": 1})
check("제외 목록의 없는 id는 경고 대상으로 알려 줌", res["missing_excluded"], ["INC-GONE"])
check("층 판별: 중복 결제를 INGEST로 잘못 말함", [x["status"] for x in res["layer"]], ["OK", "OK", "WRONG"])
check("근거 연결: 주장 6개 중 4개", (res["evidence"]["claims"], res["evidence"]["backed"], res["evidence"]["ratio"]), (6, 4, 0.667))

# --- 재처리 뒤 다시 판정한 줄은 채점에서 빠진다 ---
check("순찰 기록이 있으면 REDETECT 줄 제외", len(regular_rows(anoms, runs)), 9)
check("순찰 기록이 없어도 run_id의 -RD- 로 제외", len(regular_rows(anoms)), 9)

# --- 허용 지연을 바꾸면 결과가 바뀐다 ---
res2 = score(inc, anoms, runs, None, allow={"DATA_POLLUTION/DUPLICATE_SUCCESS_PAYMENT": 15}, excluded=excluded)
check("성공 결제 중복 허용을 15분으로 늘리면 3/3", (res2["detected"], res2["total"]), (3, 3))
check("종류 이름만 줘도 바뀜(SINK_PAUSE=20이면 24분은 LATE)", [d["status"] for d in score(inc, anoms, runs, None, allow={"SINK_PAUSE": 20}, excluded=excluded)["detection"]], ["OK", "LATE", "LATE"])
check("리포트가 없으면 층·근거는 채점 안 함", "layer" in res2, False)


# --- 직접 만든 경우들 ---
def anomaly(aid, atype, st, sk, det):
    return {"run_id": "r-" + aid, "anomaly_id": aid, "anomaly_type": atype, "scope_type": st, "scope_key": sk,
            "window_start": det, "window_end": det, "detected_at": det}


pg = [inc[0]]
det, _ = score_detection(pg, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_B", "2026-10-20 15:10:00")])
check("대상이 다르면(PG_B) 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(pg, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 14:50:00")])
check("사건 시작 전에 울린 것은 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(pg, [anomaly("x", "BRONZE_LAG_SPIKE", "topic", "payments", "2026-10-20 15:10:00")])
check("종류가 다른 이상은 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(pg, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:00:00")])
check("시작과 같은 시각은 0분 만에 잡음", (det[0]["status"], det[0]["delay_min"]), ("OK", 0.0))
det, _ = score_detection(pg, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:50:00")])
check("끝 뒤 허용 지연의 2배(40분)를 넘기면 못 잡은 것", det[0]["status"], "MISSED")
det, _ = score_detection(pg, [anomaly("x", "PG_FAILURE_SPIKE", "pg", "PG_A", "2026-10-20 15:35:00")])
check("허용 지연(15분)은 넘겼지만 2배 안이면 늦게 잡은 것", (det[0]["status"], det[0]["delay_min"]), ("LATE", 35.0))

# --- 끝 기록이 아직 없는 사건(진행 중) ---
tmp = os.path.join(HERE, ".tmp_open")
os.makedirs(tmp, exist_ok=True)
json.dump({"schema_version": 1, "incident_id": "INC-OPEN", "phase": "start", "type": "SINK_PAUSE", "at": "2026-10-20T16:00:00Z",
           "params": {"connector": "bronze-s3-sink-v2", "planned_minutes": 35}}, open(os.path.join(tmp, "a_start.json"), "w"))
open_inc = load_incidents(tmp)
check("끝 기록이 없으면 open이고 끝 = 시작", (open_inc[0]["open"], open_inc[0]["end"] == open_inc[0]["start"]), (True, True))
os.remove(os.path.join(tmp, "a_start.json"))
os.rmdir(tmp)

# --- 모르는 사건 종류는 오류 없이 채점에서 제외 ---
weird = [{"incident_id": "X", "type": "NEW_THING", "key": "NEW_THING", "params": {}, "start": inc[0]["start"], "end": inc[0]["end"], "open": False}]
check("모르는 사건 종류는 제외하고 이유를 남김", [(i["incident_id"], why.startswith("모르는")) for i, why in split_incidents(weird)[1]], [("X", True)])

# --- 실제 시험 기록 제외 목록 ---
real = load_excluded(DEFAULT_EXCLUDE_FILE)
check("기본 제외 목록에 시험 사건 4건", len(real), 4)
check("제외 목록 파일의 주석(#)은 id에 안 들어감", all("#" not in x and " " not in x for x in real), True)

# --- 명령줄 실행 ---
out = subprocess.run([sys.executable, os.path.join(HERE, "score.py"), "--incidents", os.path.join(S, "incident_log"),
                      "--anomalies", os.path.join(S, "anomalies.json"), "--runs", os.path.join(S, "detection_runs.json"),
                      "--reports", os.path.join(S, "reports.json"), "--exclude-file", os.path.join(S, "excluded_incidents.txt")],
                     capture_output=True, text=True)
check("명령줄 실행이 성공하고 요약이 나옴", (out.returncode, "탐지 적발: 2/3" in out.stdout, "채점하지 않은 사건 3건" in out.stdout), (0, True, True))
check("S3 Sink 정지 허용 지연 30분 대응이 SCENARIOS에 있음", SCENARIOS["SINK_PAUSE"]["allow_min"], 30)

t_anoms = anoms + [{**anoms[0], "anomaly_id": "a-test-0001", "run_id": "t"}]
t_reports = reports + [{"anomaly_id": "a-test-0001", "layer": "UNKNOWN"}]
base_res = score(inc, anoms, runs, reports, excluded=excluded)
test_res = score(inc, t_anoms, runs, t_reports, excluded=excluded)
check("a-test- 이상 줄과 리포트는 채점·오탐에 영향 없음", (test_res["false_alarms"], test_res["detected"], test_res.get("layer")), (base_res["false_alarms"], base_res["detected"], base_res.get("layer")))

print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
