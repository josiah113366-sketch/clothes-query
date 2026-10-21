"""채점 스크립트: 정답표(incident_log)와 이상 이력(anomaly)·원인 리포트를 비교해 점수를 낸다.

채점 항목 4가지 (설계 문서 docs/design/agent/anomaly-answer-key.md 8절)
  1. 탐지 적발   정답표의 장애 시작 뒤 허용 지연 안에 같은 종류의 이상이 기록됐나
  2. 오탐        장애와 상관없는 시간·대상에 기록된 이상 (건수와 덩어리 수)
  3. 층 판별     리포트가 말한 원인 층이 정답표의 정답 층과 같은가
  4. 근거 연결   리포트의 주장마다 근거가 붙어 있나

이 스크립트는 정답표를 읽는다. 조사 에이전트는 정답표를 읽을 수 없으므로(권한 분리), 채점은 에이전트 밖에서 사람이 돌린다.
"""
import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone

# 정답표 사건 종류별 채점 기준. 정답표는 시뮬레이터 컨트롤러가 쓴 기록이다 (simulator/src/sim/controller).
#   PG_OUTAGE·INGEST_LAG는 종류만으로, DATA_POLLUTION은 start 기록의 params.kind로 기준을 고른다.
#   allow_min = 허용 지연(분, 제안·팀 결정 대기). rule=False는 아직 탐지 규칙이 없는 종류다.
SCENARIOS = {
    "PG_OUTAGE": {"anomaly_type": "PG_FAILURE_SPIKE", "layer": "PAYMENT", "allow_min": 15, "rule": True},
    "INGEST_LAG": {"anomaly_type": "BRONZE_LAG_SPIKE", "layer": "INGEST", "allow_min": 10, "rule": True},
    "DUPLICATE_SUCCESS_PAYMENT": {"anomaly_type": "DUPLICATE_SUCCESS_PAYMENT", "layer": "DATA_QUALITY", "allow_min": 10, "rule": True},
    "ORDER_TOTAL_MISMATCH": {"anomaly_type": "ORDER_TOTAL_MISMATCH", "layer": "DATA_QUALITY", "allow_min": 10, "rule": False},
}
# 채점 대상이 아닌 사건: 약한 급증(medium 모드)과 시뮬레이터 일시 정지. 이 구간에 울린 이상은 오탐으로 센다.
NOT_SCORED = {"TRAFFIC_SURGE", "OPERATOR_PAUSE"}
RELATED_FACTOR = 2     # 사건 끝 뒤 (허용 지연 x 이 값)까지 울린 이상은 그 사건에 대한 것으로 본다. 허용 지연을 넘기면 LATE (임의 값)
EPISODE_GAP_MIN = 15   # 같은 종류·같은 대상의 이상이 이 시간 안에 이어지면 한 덩어리로 센다 (임의 값)


def parse_time(value):
    """'2026-10-20T15:00:00Z', '2026-10-20 15:00:00', '+09:00' 붙은 시각을 UTC 기준 naive datetime으로."""
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _read_records(path):
    files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".json")] if os.path.isdir(path) else [path]
    out = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        out += data if isinstance(data, list) else [data]
    return out


def load_incidents(path):
    """정답표: 컨트롤러가 쓴 start·end 기록(파일 하나당 기록 하나)을 incident_id로 짝지어 사건 하나로 만든다.

    돌려주는 사건: incident_id, type, scenario(채점 기준 이름), injected_start, injected_end, ended_by,
    params, result, scope(("pg","PG_A") 또는 None), expected_layer. 채점 대상이 아니면 scenario가 None이다.
    """
    starts, ends = {}, {}
    for r in _read_records(path):
        (starts if r["phase"] == "start" else ends)[r["incident_id"]] = r
    out = []
    for iid, st in sorted(starts.items(), key=lambda kv: kv[1]["at"]):
        en = ends.get(iid)
        params = st.get("params") or {}
        start = parse_time(st["at"])
        if en:
            end = parse_time(en["at"])
        else:   # 끝 기록이 없다(비정상 종료): 계획한 시간만큼 이어졌다고 본다
            end = start + timedelta(minutes=params.get("planned_minutes", 0))
        kind = st["type"] if st["type"] != "DATA_POLLUTION" else params.get("kind")
        ended_by = en.get("ended_by") if en else None
        scenario = kind if kind in SCENARIOS and ended_by != "failed" else None
        if scenario is None and st["type"] not in NOT_SCORED and ended_by != "failed":
            raise ValueError(f"모르는 사건 종류입니다: {st['type']} {kind}")
        out.append({"incident_id": iid, "type": st["type"], "scenario": scenario, "injected_start": start, "injected_end": end,
                    "ended_by": ended_by, "params": params, "result": (en or {}).get("result", {}),
                    "scope": ("pg", params["pg"]) if st["type"] == "PG_OUTAGE" and params.get("pg") else None,
                    "expected_layer": SCENARIOS[scenario]["layer"] if scenario else None})
    return out


def load_rows(path):
    """이상 이력·순찰 기록: JSON 목록, JSON Lines, CSV."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".csv"):
        return list(csv.DictReader(text.splitlines()))
    text = text.strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _scope(row):
    return f"{row.get('scope_type')}={row.get('scope_key')}"


def _scope_matches(incident, row):
    want = incident.get("scope")
    return want is None or (row.get("scope_type"), row.get("scope_key")) == tuple(want)


def _detected(row):
    return parse_time(row.get("detected_at") or row["window_end"])


def regular_rows(anomalies, runs=None):
    """처음 판정한 줄만 채점한다. 재처리 뒤 다시 판정한 줄은 제외한다."""
    if runs is not None:
        regular = {r["run_id"] for r in runs if r.get("kind") == "REGULAR"}
        return [a for a in anomalies if a["run_id"] in regular]
    return [a for a in anomalies if "-RD-" not in str(a.get("run_id", ""))]


def score_detection(incidents, anomalies, allow=None):
    allow = allow or {}
    results, related_ids = [], set()
    for inc in incidents:
        if inc["scenario"] is None:      # 채점 대상이 아닌 사건(약한 급증, 일시 정지, 적용 실패)
            continue
        spec = SCENARIOS[inc["scenario"]]
        limit = timedelta(minutes=allow.get(inc["scenario"], spec["allow_min"]))
        start, end = inc["injected_start"], inc["injected_end"]
        if not spec["rule"]:             # 아직 탐지 규칙이 없는 종류: 못 잡은 것으로 세지 않고 따로 보고한다
            results.append({"incident_id": inc["incident_id"], "scenario": inc["scenario"], "status": "NO_RULE",
                            "delay_min": None, "allow_min": limit.total_seconds() / 60, "anomaly_ids": []})
            continue
        cands = [a for a in anomalies if a["anomaly_type"] == spec["anomaly_type"] and _scope_matches(inc, a)
                 and start <= _detected(a) <= end + RELATED_FACTOR * limit]
        related_ids.update(a["anomaly_id"] for a in cands)
        if not cands:
            results.append({"incident_id": inc["incident_id"], "scenario": inc["scenario"], "status": "MISSED",
                            "delay_min": None, "allow_min": limit.total_seconds() / 60, "anomaly_ids": []})
            continue
        first = min(cands, key=_detected)
        delay = (_detected(first) - start).total_seconds() / 60
        results.append({"incident_id": inc["incident_id"], "scenario": inc["scenario"],
                        "status": "OK" if delay <= limit.total_seconds() / 60 else "LATE",
                        "delay_min": round(delay, 1), "allow_min": limit.total_seconds() / 60,
                        "anomaly_ids": sorted({a["anomaly_id"] for a in cands})})
    return results, related_ids


def score_false_alarms(anomalies, related_ids):
    """장애와 상관없는 이상. 건수(고유 anomaly_id)와, 이어진 것을 합친 덩어리 수."""
    stray = {}
    for a in anomalies:
        if a["anomaly_id"] not in related_ids:
            stray.setdefault(a["anomaly_id"], a)
    groups, episodes = {}, 0
    for a in sorted(stray.values(), key=_detected):
        key = (a["anomaly_type"], _scope(a))
        t = _detected(a)
        if key not in groups or t - groups[key] > timedelta(minutes=EPISODE_GAP_MIN):
            episodes += 1
        groups[key] = t
    return {"count": len(stray), "episodes": episodes}


def score_reports(incidents, detection, reports):
    """층 판별과 근거 연결. 리포트는 anomaly_id로 이상 이력과 이어진다(에이전트는 incident_id를 모른다)."""
    by_incident = {d["incident_id"]: set(d["anomaly_ids"]) for d in detection}
    layer, claims_total, claims_backed = [], 0, 0
    for inc in incidents:
        if inc["scenario"] is None or not SCENARIOS[inc["scenario"]]["rule"]:
            continue
        linked = [r for r in reports if r.get("incident_id") == inc["incident_id"]
                  or r.get("anomaly_id") in by_incident[inc["incident_id"]]]
        if not linked:
            layer.append({"incident_id": inc["incident_id"], "status": "NO_REPORT", "said": None, "expected": inc["expected_layer"]})
        else:
            said = linked[-1].get("cause_layer")
            layer.append({"incident_id": inc["incident_id"], "status": "OK" if said == inc["expected_layer"] else "WRONG",
                          "said": said, "expected": inc["expected_layer"]})
        for r in linked:
            for c in r.get("claims", []):
                if c.get("kind") == "ASSUMPTION":      # 추정은 근거가 없어도 감점하지 않는다 (확인된 사실만 센다)
                    continue
                claims_total += 1
                claims_backed += 1 if c.get("evidence") else 0
    return layer, {"claims": claims_total, "backed": claims_backed,
                   "ratio": round(claims_backed / claims_total, 3) if claims_total else None}


def score(incidents, anomalies, runs=None, reports=None, allow=None):
    rows = regular_rows(anomalies, runs)
    detection, related = score_detection(incidents, rows, allow)
    summary = {"detection": detection, "false_alarms": score_false_alarms(rows, related),
               "detected": sum(d["status"] == "OK" for d in detection),
               "total": sum(d["status"] != "NO_RULE" for d in detection),
               "no_rule": sum(d["status"] == "NO_RULE" for d in detection),
               "not_scored": sum(i["scenario"] is None for i in incidents)}
    if reports is not None:
        summary["layer"], summary["evidence"] = score_reports(incidents, detection, reports)
    return summary


def format_report(s):
    names = {"PG_OUTAGE": "PG 장애", "INGEST_LAG": "소비 지연", "DUPLICATE_SUCCESS_PAYMENT": "한 주문에 성공 결제 2건",
             "ORDER_TOTAL_MISMATCH": "주문 총액 불일치"}
    status = {"OK": "맞게 잡음", "LATE": "잡았지만 늦음", "MISSED": "못 잡음", "NO_RULE": "탐지 규칙이 아직 없음(점수에서 뺌)"}
    lines = [f"탐지 적발: {s['detected']}/{s['total']}개 사건을 허용 시간 안에 잡았습니다."]
    for d in s["detection"]:
        if d["status"] == "NO_RULE":
            lines.append(f"  - {d['incident_id']} {names[d['scenario']]}: {status[d['status']]}")
            continue
        when = f"{d['delay_min']}분 만에" if d["delay_min"] is not None else "-"
        lines.append(f"  - {d['incident_id']} {names[d['scenario']]}: {status[d['status']]} ({when}, 허용 {d['allow_min']:.0f}분)")
    if s["not_scored"]:
        lines.append(f"채점 대상이 아닌 사건 {s['not_scored']}건(약한 급증·일시 정지·적용 실패): 이 구간에 울린 이상은 오탐으로 셉니다.")
    fa = s["false_alarms"]
    lines.append(f"오탐: 장애와 상관없는 이상이 {fa['count']}건(이어진 것을 합치면 {fa['episodes']}덩어리)입니다.")
    if "layer" in s:
        ok = sum(x["status"] == "OK" for x in s["layer"])
        lines.append(f"층 판별: {ok}/{len(s['layer'])}개 사건의 원인 층을 맞혔습니다.")
        for x in s["layer"]:
            lines.append(f"  - {x['incident_id']}: 정답 {x['expected']}, 리포트 {x['said'] or '없음'} → {x['status']}")
        e = s["evidence"]
        ratio = "-" if e["ratio"] is None else f"{e['ratio'] * 100:.0f}%"
        lines.append(f"근거 연결: 주장 {e['claims']}개 중 {e['backed']}개에 근거가 있습니다 ({ratio}).")
    else:
        lines.append("층 판별·근거 연결: 리포트가 없어서 채점하지 않았습니다.")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="정답표와 이상 이력·리포트를 비교해 채점합니다.")
    p.add_argument("--incidents", required=True, help="정답표 폴더(컨트롤러가 쓴 start·end JSON 파일들) 또는 파일")
    p.add_argument("--anomalies", required=True, help="이상 이력 (JSON 목록, JSON Lines, CSV)")
    p.add_argument("--runs", help="순찰 기록(detection_runs). 있으면 처음 판정한 줄만 채점")
    p.add_argument("--reports", help="원인 리포트 (JSON 목록)")
    p.add_argument("--allow", help="허용 지연(분) 덮어쓰기. 예: PG_OUTAGE=15,INGEST_LAG=10,DUPLICATE_SUCCESS_PAYMENT=10")
    p.add_argument("--json", action="store_true", help="요약을 JSON으로 출력")
    a = p.parse_args(argv)
    allow = {k: float(v) for k, v in (x.split("=") for x in a.allow.split(","))} if a.allow else None
    reports = json.load(open(a.reports, encoding="utf-8")) if a.reports else None
    s = score(load_incidents(a.incidents), load_rows(a.anomalies), load_rows(a.runs) if a.runs else None, reports, allow)
    print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else format_report(s))
    return s


if __name__ == "__main__":
    main()
