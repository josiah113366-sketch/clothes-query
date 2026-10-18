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

# 사건 종류별: 어떤 이상 종류가 정답인지, 정답 층, 허용 지연(분, 제안·팀 결정 대기)
SCENARIOS = {
    "PG_OUTAGE": {"anomaly_type": "PG_FAILURE_SPIKE", "layer": "PAYMENT", "allow_min": 15},
    "INGEST_LAG": {"anomaly_type": "BRONZE_LAG_SPIKE", "layer": "INGEST", "allow_min": 10},
    "SCHEMA_POLLUTION": {"anomaly_type": "MALFORMED_SPIKE", "layer": "DATA_QUALITY", "allow_min": 10},
}
EPISODE_GAP_MIN = 15   # 같은 종류·같은 대상의 이상이 이 시간 안에 이어지면 한 덩어리로 센다 (임의 값)


def parse_time(value):
    """'2026-10-20T15:00:00Z', '2026-10-20 15:00:00', '+09:00' 붙은 시각을 UTC 기준 naive datetime으로."""
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_incidents(path):
    """정답표: 폴더(장애 하나당 JSON 파일 한 개)나 파일 하나. 파일이 목록이어도 받는다."""
    files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".json")] if os.path.isdir(path) else [path]
    out = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        out += data if isinstance(data, list) else [data]
    for inc in out:
        if inc["scenario"] not in SCENARIOS:
            raise ValueError(f"모르는 사건 종류입니다: {inc['scenario']}")
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
    want = incident.get("scope_key")
    if want in (None, "", "*"):
        return True
    return want == _scope(row) or want == row.get("scope_key")


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
        spec = SCENARIOS[inc["scenario"]]
        limit = timedelta(minutes=allow.get(inc["scenario"], spec["allow_min"]))
        start, end = parse_time(inc["injected_start"]), parse_time(inc["injected_end"])
        cands = [a for a in anomalies if a["anomaly_type"] == spec["anomaly_type"] and _scope_matches(inc, a)
                 and start <= _detected(a) <= end + limit]
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
                claims_total += 1
                claims_backed += 1 if c.get("evidence") else 0
    return layer, {"claims": claims_total, "backed": claims_backed,
                   "ratio": round(claims_backed / claims_total, 3) if claims_total else None}


def score(incidents, anomalies, runs=None, reports=None, allow=None):
    rows = regular_rows(anomalies, runs)
    detection, related = score_detection(incidents, rows, allow)
    summary = {"detection": detection, "false_alarms": score_false_alarms(rows, related),
               "detected": sum(d["status"] == "OK" for d in detection), "total": len(detection)}
    if reports is not None:
        summary["layer"], summary["evidence"] = score_reports(incidents, detection, reports)
    return summary


def format_report(s):
    names = {"PG_OUTAGE": "PG 장애", "INGEST_LAG": "소비 지연", "SCHEMA_POLLUTION": "스키마 오염"}
    status = {"OK": "맞게 잡음", "LATE": "잡았지만 늦음", "MISSED": "못 잡음"}
    lines = [f"탐지 적발: {s['detected']}/{s['total']}개 사건을 허용 시간 안에 잡았습니다."]
    for d in s["detection"]:
        when = f"{d['delay_min']}분 만에" if d["delay_min"] is not None else "-"
        lines.append(f"  - {d['incident_id']} {names[d['scenario']]}: {status[d['status']]} ({when}, 허용 {d['allow_min']:.0f}분)")
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
    p.add_argument("--incidents", required=True, help="정답표 폴더(JSON 한 건당 파일 하나) 또는 파일")
    p.add_argument("--anomalies", required=True, help="이상 이력 (JSON 목록, JSON Lines, CSV)")
    p.add_argument("--runs", help="순찰 기록(detection_runs). 있으면 처음 판정한 줄만 채점")
    p.add_argument("--reports", help="원인 리포트 (JSON 목록)")
    p.add_argument("--allow", help="허용 지연(분) 덮어쓰기. 예: PG_OUTAGE=15,INGEST_LAG=10,SCHEMA_POLLUTION=10")
    p.add_argument("--json", action="store_true", help="요약을 JSON으로 출력")
    a = p.parse_args(argv)
    allow = {k: float(v) for k, v in (x.split("=") for x in a.allow.split(","))} if a.allow else None
    reports = json.load(open(a.reports, encoding="utf-8")) if a.reports else None
    s = score(load_incidents(a.incidents), load_rows(a.anomalies), load_rows(a.runs) if a.runs else None, reports, allow)
    print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else format_report(s))
    return s


if __name__ == "__main__":
    main()
