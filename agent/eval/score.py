"""채점 스크립트: 정답표(incident_log)와 이상 이력(anomaly)·원인 리포트를 비교해 점수를 낸다.

채점 항목 4가지 (설계 문서 docs/design/agent/anomaly-answer-key.md 8절)
  1. 탐지 적발   사건 시작 뒤 허용 지연 안에 같은 종류의 이상이 기록됐나
  2. 오탐        사건과 상관없는 시간·대상에 기록된 이상 (건수와 덩어리 수)
  3. 층 판별     리포트가 말한 원인 층이 정답 층과 같은가
  4. 근거 연결   리포트의 주장마다 근거가 붙어 있나

정답표는 시뮬레이터 컨트롤러가 쓴 실제 형식이다. 사건 하나가 파일 두 개(start, end)이고, 파일 이름은
YYYYMMDDTHHMMSSZ_<incident_id>_<phase>.json 이다 (simulator/src/sim/controller/log.py). 시각은 UTC다.
이 스크립트는 정답표를 읽는다. 조사 에이전트는 정답표를 읽을 수 없으므로(권한 분리), 채점은 에이전트 밖에서 사람이 돌린다.
"""
import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone

# 사건(종류 또는 종류/kind)별 정답: 어떤 이상 종류가 정답인지, 정답 층, 허용 지연(분), 이름.
# 허용 지연은 팀 공지로 확정(2026-10-23)했고 소비 지연은 S3 Sink 정지로 바뀌어 30분이다(파일 전환 15분 기준 최악 약 26분).
SCENARIOS = {
    "PG_OUTAGE": {"anomaly_type": "PG_FAILURE_SPIKE", "layer": "PAYMENT", "allow_min": 15, "name": "PG 장애"},
    "SINK_PAUSE": {"anomaly_type": "BRONZE_LAG_SPIKE", "layer": "INGEST", "allow_min": 30, "name": "S3 Sink 정지(소비 지연)"},
    "DATA_POLLUTION/DUPLICATE_SUCCESS_PAYMENT": {"anomaly_type": "DUPLICATE_SUCCESS_PAYMENT", "layer": "DATA_QUALITY",
                                                 "allow_min": 10, "name": "성공 결제 중복"},
    # 규칙(R6)은 있지만 Silver 정기 실행이 정해지기 전까지 기본으로 채점하지 않는다. --include로 켠다.
    "DATA_POLLUTION/ORDER_TOTAL_MISMATCH": {"anomaly_type": "ORDER_TOTAL_MISMATCH", "layer": "DATA_QUALITY",
                                            "allow_min": 30, "name": "주문 총액 불일치", "default_off": True},
}
# 채점하지 않는 사건 (이유). 이 사건 앞뒤에 울린 이상은 오탐으로 세지 않는다.
NOT_GRADED = {
    "INGEST_LAG": "burst 모드는 S3 Sink가 모두 소화해 소비 지연이 생기지 않는다",
    "TRAFFIC_SURGE": "medium 모드는 약한 급증이라 채점하지 않는다",
    "OPERATOR_PAUSE": "시뮬레이터를 멈춘 기록이라 사건이 아니다",
}
EPISODE_GAP_MIN = 15      # 같은 종류·같은 대상의 이상이 이 시간 안에 이어지면 한 덩어리로 센다 (임의 값)
LATE_FACTOR = 2           # 사건 끝 뒤 허용 지연의 이 배수까지 울린 이상을 그 사건의 것으로 본다 (임의 값)
MUTE_MIN = 30             # 채점 제외·미채점 사건이 끝난 뒤 이 시간 안에 울린 이상은 오탐으로 세지 않는다 (임의 값)
DEFAULT_EXCLUDE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "excluded_incidents.txt")


def parse_time(value):
    """'2026-10-20T15:00:00Z', '2026-10-20 15:00:00', '+09:00' 붙은 시각을 UTC 기준 naive datetime으로."""
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def scenario_key(record):
    """정답표 레코드의 사건 이름. 데이터 오염은 kind까지 붙인다."""
    if record["type"] == "DATA_POLLUTION":
        return f"DATA_POLLUTION/{(record.get('params') or {}).get('kind')}"
    return record["type"]


def load_incidents(path):
    """정답표 폴더(파일 하나가 start 또는 end 기록)나 파일 하나를 읽어 사건 하나당 한 건으로 합친다.

    end 기록이 아직 없으면(진행 중) 끝은 시작과 같게 두고 open=True로 표시한다."""
    files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".json")] if os.path.isdir(path) else [path]
    records = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        records += data if isinstance(data, list) else [data]
    starts = {r["incident_id"]: r for r in records if r.get("phase") == "start"}
    ends = {r["incident_id"]: r for r in records if r.get("phase") == "end"}
    out = []
    for iid, s in sorted(starts.items(), key=lambda kv: kv[1]["at"]):
        e = ends.get(iid)
        out.append({"incident_id": iid, "type": s["type"], "key": scenario_key(s), "params": s.get("params") or {},
                    "start": parse_time(s["at"]), "end": parse_time(e["at"]) if e else parse_time(s["at"]),
                    "open": e is None, "ended_by": e.get("ended_by") if e else None, "result": (e or {}).get("result") or {}})
    return out


def load_excluded(path):
    """채점에서 뺄 사건 id 목록. 한 줄에 id 하나, '#' 뒤는 이유(주석)."""
    if not path or not os.path.exists(path):
        return set()
    ids = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            token = line.split("#", 1)[0].strip()
            if token:
                ids.add(token)
    return ids


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
    """PG 장애는 장애를 건 PG의 이상만 맞는 것으로 본다. 나머지 사건은 대상을 따지지 않는다."""
    want = incident["params"].get("pg") if incident["type"] == "PG_OUTAGE" else None
    return want is None or want == row.get("scope_key")


def _detected(row):
    return parse_time(row.get("detected_at") or row["window_end"])


def regular_rows(anomalies, runs=None):
    """처음 판정한 줄만 채점한다. 재처리 뒤 다시 판정한 줄은 제외한다."""
    if runs is not None:
        regular = {r["run_id"] for r in runs if r.get("kind") == "REGULAR"}
        return [a for a in anomalies if a["run_id"] in regular]
    return [a for a in anomalies if "-RD-" not in str(a.get("run_id", ""))]


def split_incidents(incidents, excluded=(), include=()):
    """(채점할 사건, 채점하지 않는 사건 [(사건, 이유)])로 나눈다."""
    graded, skipped = [], []
    for inc in incidents:
        spec = SCENARIOS.get(inc["key"])
        if inc["incident_id"] in excluded:
            skipped.append((inc, "채점 제외 목록(시험 기록)"))
        elif inc["type"] in NOT_GRADED:
            skipped.append((inc, NOT_GRADED[inc["type"]]))
        elif spec is None:
            skipped.append((inc, f"모르는 사건 종류({inc['key']})"))
        elif spec.get("default_off") and inc["key"].split("/")[-1] not in include and inc["key"] not in include:
            skipped.append((inc, "Silver 정기 실행이 정해질 때까지 채점하지 않음(--include로 켬)"))
        else:
            graded.append(inc)
    return graded, skipped


def _allow_min(inc, allow):
    allow = allow or {}
    return allow.get(inc["key"], allow.get(inc["type"], SCENARIOS[inc["key"]]["allow_min"]))


def score_detection(incidents, anomalies, allow=None):
    results, related_ids = [], set()
    for inc in incidents:
        spec = SCENARIOS[inc["key"]]
        limit = timedelta(minutes=_allow_min(inc, allow))
        cands = [a for a in anomalies if a["anomaly_type"] == spec["anomaly_type"] and _scope_matches(inc, a)
                 and inc["start"] <= _detected(a) <= inc["end"] + limit * LATE_FACTOR]
        related_ids.update(a["anomaly_id"] for a in cands)
        base = {"incident_id": inc["incident_id"], "key": inc["key"], "allow_min": limit.total_seconds() / 60, "open": inc["open"]}
        if not cands:
            results.append({**base, "status": "MISSED", "delay_min": None, "anomaly_ids": []})
            continue
        first = min(cands, key=_detected)
        delay = (_detected(first) - inc["start"]).total_seconds() / 60
        results.append({**base, "status": "OK" if delay <= limit.total_seconds() / 60 else "LATE", "delay_min": round(delay, 1),
                        "anomaly_ids": sorted({a["anomaly_id"] for a in cands})})
    return results, related_ids


def muted_windows(skipped, allow=None):
    """채점하지 않는 사건의 시간대. 이 안에서 울린 이상은 오탐으로 세지 않는다."""
    out = []
    for inc, _ in skipped:
        spec = SCENARIOS.get(inc["key"])
        after = max(MUTE_MIN, (_allow_min(inc, allow) * LATE_FACTOR) if spec else 0)
        out.append((inc["start"], inc["end"] + timedelta(minutes=after)))
    return out


def score_false_alarms(anomalies, related_ids, muted=()):
    """사건과 상관없는 이상. 건수(고유 anomaly_id)와, 이어진 것을 합친 덩어리 수. 채점하지 않는 사건 시간대의 이상은 뺀다."""
    stray = {}
    for a in anomalies:
        t = _detected(a)
        if a["anomaly_id"] in related_ids or any(lo <= t <= hi for lo, hi in muted):
            continue
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
        expected = SCENARIOS[inc["key"]]["layer"]
        linked = [r for r in reports if r.get("incident_id") == inc["incident_id"]
                  or r.get("anomaly_id") in by_incident[inc["incident_id"]]]
        if not linked:
            layer.append({"incident_id": inc["incident_id"], "status": "NO_REPORT", "said": None, "expected": expected})
        else:
            said = linked[-1].get("cause_layer")
            layer.append({"incident_id": inc["incident_id"], "status": "OK" if said == expected else "WRONG",
                          "said": said, "expected": expected})
        for r in linked:
            for c in r.get("claims", []):
                claims_total += 1
                claims_backed += 1 if c.get("evidence") else 0
    return layer, {"claims": claims_total, "backed": claims_backed,
                   "ratio": round(claims_backed / claims_total, 3) if claims_total else None}


def score(incidents, anomalies, runs=None, reports=None, allow=None, excluded=(), include=()):
    graded, skipped = split_incidents(incidents, excluded, include)
    rows = regular_rows(anomalies, runs)
    detection, related = score_detection(graded, rows, allow)
    summary = {"detection": detection, "false_alarms": score_false_alarms(rows, related, muted_windows(skipped, allow)),
               "detected": sum(d["status"] == "OK" for d in detection), "total": len(detection),
               "skipped": [{"incident_id": i["incident_id"], "key": i["key"], "reason": why} for i, why in skipped],
               "missing_excluded": sorted(set(excluded) - {i["incident_id"] for i in incidents})}
    if reports is not None:
        summary["layer"], summary["evidence"] = score_reports(graded, detection, reports)
    return summary


def format_report(s):
    status = {"OK": "맞게 잡음", "LATE": "잡았지만 늦음", "MISSED": "못 잡음"}
    lines = [f"탐지 적발: {s['detected']}/{s['total']}개 사건을 허용 시간 안에 잡았습니다."]
    for d in s["detection"]:
        when = f"{d['delay_min']}분 만에" if d["delay_min"] is not None else "-"
        tail = ", 끝 기록 없음(진행 중)" if d["open"] else ""
        lines.append(f"  - {d['incident_id']} {SCENARIOS[d['key']]['name']}: {status[d['status']]} ({when}, 허용 {d['allow_min']:.0f}분{tail})")
    fa = s["false_alarms"]
    lines.append(f"오탐: 사건과 상관없는 이상이 {fa['count']}건(이어진 것을 합치면 {fa['episodes']}덩어리)입니다.")
    if s["skipped"]:
        lines.append(f"채점하지 않은 사건 {len(s['skipped'])}건 (앞뒤에 울린 이상은 오탐으로 세지 않음):")
        for x in s["skipped"]:
            lines.append(f"  - {x['incident_id']} {x['key']}: {x['reason']}")
    if s["missing_excluded"]:
        lines.append("주의: 제외 목록에 있지만 정답표에서 찾지 못한 id가 있습니다(id를 잘못 옮겼거나 정답표가 아직 안 내려졌을 수 있음): "
                     + ", ".join(s["missing_excluded"]))
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
    p.add_argument("--incidents", required=True, help="정답표 폴더(start·end 기록 파일들) 또는 파일")
    p.add_argument("--anomalies", required=True, help="이상 이력 (JSON 목록, JSON Lines, CSV)")
    p.add_argument("--runs", help="순찰 기록(detection_runs). 있으면 처음 판정한 줄만 채점")
    p.add_argument("--reports", help="원인 리포트 (JSON 목록)")
    p.add_argument("--allow", help="허용 지연(분) 덮어쓰기. 예: PG_OUTAGE=15,SINK_PAUSE=30,DATA_POLLUTION/DUPLICATE_SUCCESS_PAYMENT=10")
    p.add_argument("--exclude-file", default=DEFAULT_EXCLUDE_FILE, help="채점에서 뺄 사건 id 목록(기본: excluded_incidents.txt)")
    p.add_argument("--exclude", help="채점에서 더 뺄 사건 id (쉼표로 구분)")
    p.add_argument("--include", help="기본으로 채점하지 않는 사건을 켠다. 예: ORDER_TOTAL_MISMATCH")
    p.add_argument("--json", action="store_true", help="요약을 JSON으로 출력")
    a = p.parse_args(argv)
    allow = {k: float(v) for k, v in (x.split("=") for x in a.allow.split(","))} if a.allow else None
    excluded = load_excluded(a.exclude_file) | {x.strip() for x in (a.exclude or "").split(",") if x.strip()}
    include = {x.strip() for x in (a.include or "").split(",") if x.strip()}
    reports = json.load(open(a.reports, encoding="utf-8")) if a.reports else None
    s = score(load_incidents(a.incidents), load_rows(a.anomalies), load_rows(a.runs) if a.runs else None, reports, allow, excluded, include)
    print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else format_report(s))
    return s


if __name__ == "__main__":
    main()
