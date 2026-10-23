"""판정 잡 틀: 5분마다 한 번 실행되는 "순찰" 한 바퀴.

한 바퀴(run_once)가 하는 일
  1. 지금 시각을 5분 단위로 내려 순찰 번호(run_id)를 정한다. 이미 돈 번호면 건너뛴다.
  2. 원장·뷰를 읽어 규칙 R1·R3·R4·R5로 판정한다.
  3. 이상 줄을 gold_b.anomaly 에 **새 줄로 쌓는다**(지우거나 덮지 않는다). 순찰 기록(detection_runs)도 남긴다.
  4. 재처리 기록(reprocess_events)에 "교체 끝났는데 아직 재판정 안 한" 줄이 있으면 그 시간대를 다시 판정하고
     REDETECTED, VERIFIED 줄을 남긴다. (Airflow가 재처리 뒤에 이 잡을 바로 이어 붙이기 전까지의 임시 방식)

바깥 세상과는 두 개의 함수로만 만난다 (그래서 가짜 데이터로 시험할 수 있다)
  query(sql) -> 줄 목록(dict),  write(표 이름, 줄 목록) -> 새 줄 추가
"""
import json
import re
from datetime import datetime, timedelta

from rules import R6_RULE, Config, open_orders, r1_pg_failures, r3_bronze_lag, r4_malformed, r5_duplicate_success, r6_order_total

STEP_MIN = 5     # 판정 주기 (제안)
ACTOR = "detect_job"


def floor_tick(now: datetime) -> datetime:
    return now.replace(minute=now.minute - now.minute % STEP_MIN, second=0, microsecond=0)


def _ts(dt, cfg):
    text = dt.strftime("%Y-%m-%d %H:%M:%S")
    return f"TIMESTAMP '{text}'" if cfg.dialect == "athena" else f"'{text}'"


def _in(col, a, b, cfg):
    return f"{col} >= {_ts(a, cfg)} AND {col} < {_ts(b, cfg)}"


def _seen(as_of, cfg):
    """판정 시점에 이미 쌓여 있던 줄만 본다(그때 본 숫자를 재현). 재판정은 교체된 새 줄을 봐야 해서 걸지 않는다."""
    return f" AND loaded_at <= {_ts(as_of, cfg)}" if as_of else ""


def _r3(query, cfg, run_id, now, tick, w3, as_of):
    """R3: 최근 5분의 지연 측정, 측정 줄이 연속으로 없는지, 증거로 붙일 유입량(R2)."""
    lag_rows = query(f"""SELECT topic, MAX(lag_sec) AS max_lag_sec FROM gold_b.bronze_lag_snapshots
WHERE {_in('collected_at', tick - timedelta(minutes=2), tick, cfg)} GROUP BY topic""")
    snap_rows = query(f"""SELECT topic, COUNT(*) AS snapshots FROM gold_b.bronze_lag_snapshots
WHERE {_in('collected_at', tick - timedelta(minutes=cfg.miss_min), tick, cfg)} GROUP BY topic""")
    vol_now = query(f"SELECT topic, COUNT(*) AS n FROM gold_b.topic_messages WHERE {_in('kafka_timestamp', *w3, cfg)}{_seen(as_of, cfg)} GROUP BY topic")
    vol_prev = query(f"SELECT topic, COUNT(*) AS n FROM gold_b.topic_messages WHERE {_in('kafka_timestamp', w3[0] - timedelta(minutes=STEP_MIN), w3[0], cfg)}{_seen(as_of, cfg)} GROUP BY topic")
    ingest = {t: (next((r["n"] for r in vol_now if r["topic"] == t), 0), next((r["n"] for r in vol_prev if r["topic"] == t), 0)) for t in cfg.topics}
    return r3_bronze_lag(cfg, run_id, now, w3, {r["topic"]: r["max_lag_sec"] for r in lag_rows},
                         {r["topic"]: r["snapshots"] for r in snap_rows}, ingest)


def _replaced_filter(query, cfg, tick):
    """최근 5분 안에 교체가 끝난 시간대(LEDGER_REPLACED)의 줄 중, 교체 때 적재된 줄(loaded_at <= 교체 기록 시각)을 빼는 조건."""
    events = query(f"""SELECT window_start, window_end, "at" AS replaced_at FROM gold_b.reprocess_events
WHERE step = 'LEDGER_REPLACED' AND "at" >= {_ts(tick - timedelta(minutes=STEP_MIN), cfg)}""")
    parts = []
    for e in events:
        ws, we, at = (datetime.fromisoformat(str(e[k]).replace("T", " ")) for k in ("window_start", "window_end", "replaced_at"))
        parts.append(f" AND NOT (completed_at >= {_ts(ws, cfg)} AND completed_at < {_ts(we, cfg)} AND loaded_at <= {_ts(at, cfg)})")
    return "".join(parts)


_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _to_dt(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("T", " ")[:19])


def _r6(query, cfg, run_id, now):
    """R6: Silver 주문 총액 검사의 **최신 실행**만 읽는다(최신 상태 확인 방식). 설정된 표가 없으면 돌리지 않는다.
    열려 있는 주문은 이전 R6 이상 줄의 근거에서 되살린다. 같은 실행을 다시 읽어도 새 줄이 생기지 않는다."""
    table = cfg.silver_checks_table
    if not table:
        return []
    if not _TABLE_NAME.match(table) or not _ID.match(cfg.r6_check_name):
        raise ValueError("silver_checks_table 또는 r6_check_name 형식이 맞지 않습니다")
    latest = query(f"""SELECT run_id, MAX(checked_at) AS checked_at FROM {table}
WHERE check_name = '{cfg.r6_check_name}' GROUP BY run_id ORDER BY MAX(checked_at) DESC LIMIT 1""")
    if not latest:
        return []
    silver_run = {"run_id": latest[0]["run_id"], "checked_at": _to_dt(latest[0]["checked_at"])}
    if not _ID.match(str(silver_run["run_id"])):
        raise ValueError("Silver 실행 번호 형식이 맞지 않습니다")
    prior = query(f"SELECT evidence_ref FROM gold_b.anomaly WHERE rule_id = '{R6_RULE}' ORDER BY detected_at, run_id")
    opened = open_orders([p["evidence_ref"] for p in prior])
    base = f"FROM {table} WHERE run_id = '{silver_run['run_id']}' AND check_name = '{cfg.r6_check_name}'"
    cols = "order_id, status, order_total_amount, item_total_amount, amount_difference, check_version, source_manifest"
    mismatches = query(f"SELECT {cols} {base} AND status = 'MISMATCH'")
    passes = []
    ids = sorted(o for o in opened if _ID.match(str(o)))
    for i in range(0, len(ids), 200):      # 열려 있는 주문 중 PASS가 된 것만 확인한다 (정상 주문 전체를 읽지 않는다)
        chunk = ", ".join(f"'{o}'" for o in ids[i:i + 200])
        passes += query(f"SELECT {cols} {base} AND status = 'PASS' AND order_id IN ({chunk})")
    return r6_order_total(cfg, run_id, now, silver_run, mismatches, passes, opened)


def judge(query, cfg: Config, tick: datetime, run_id: str, now: datetime, as_of=None, bounds=None):
    """tick 시점의 원장을 읽어 이상 줄 목록을 돌려준다 (쓰지는 않는다).

    as_of=None이면 재판정이다. 재처리가 다시 만드는 원장(결제, 메시지, 깨진 메시지)로 만든 규칙만 돌린다(R3 제외).
    bounds=(시작, 끝)이면 재판정할 교체 구간이다. 결제 완료 시각으로 보는 R5가 이 밖은 보지 않게 한다.
    """
    wait = timedelta(minutes=cfg.ratio_wait_min)
    out = []
    # R1: 비율 조건이 있어 끝난 지 3분 지난 구간만 본다
    w1 = (tick - wait - timedelta(minutes=cfg.r1_win_min), tick - wait)
    per_pg = query(f"""SELECT pg, COUNT(*) AS attempts,
       SUM(CASE WHEN failure_cause = 'PG' THEN 1 ELSE 0 END) AS pg_cause_failures
FROM gold_b.payment_attempts
WHERE {_in('completed_at', *w1, cfg)}{_seen(as_of, cfg)}
GROUP BY pg""")
    out += r1_pg_failures(cfg, run_id, now, w1, per_pg)
    w3 = (tick - timedelta(minutes=STEP_MIN), tick)
    if as_of is not None:   # R3: 지연 측정값(bronze_lag_snapshots)은 재처리가 다시 만들지 않는다(그때만 잴 수 있다). 재판정에서는 빼서 항상 STILL_OPEN이 되는 일을 막는다
        out += _r3(query, cfg, run_id, now, tick, w3, as_of)
    # R4: 현재 형식 검사 규칙 버전의 깨진 메시지만 센다. 비율 조건이 있어 3분 대기
    w4 = (tick - wait - timedelta(minutes=cfg.r4_win_min), tick - wait)
    broken = query(f"""SELECT topic, COUNT(*) AS n FROM gold_b.malformed_messages
WHERE {_in('kafka_timestamp', *w4, cfg)} AND rule_version = '{cfg.format_rule_version}'{_seen(as_of, cfg)} GROUP BY topic""")
    total = query(f"SELECT topic, COUNT(*) AS n FROM gold_b.topic_messages WHERE {_in('kafka_timestamp', *w4, cfg)}{_seen(as_of, cfg)} GROUP BY topic")
    out += r4_malformed(cfg, run_id, now, w4, {r["topic"]: r["n"] for r in broken}, {r["topic"]: r["n"] for r in total})
    # R5: 한 주문에 성공 결제 2건. 비율 조건이 없어 기다리지 않는다.
    #   순찰은 "방금 적재된" 줄(loaded_at)을 본다. 중복 행의 completed_at은 원래 결제 시각이라 과거일 수 있다.
    #   다만 재처리가 교체한 줄은 loaded_at이 재처리 시각이라 방금 적재된 것처럼 보인다. 그 줄은 빼고(재판정이 따로 본다), 교체 뒤에 새로 적재된 줄만 센다.
    #   재판정은 교체된 시간대의 줄을 봐야 해서 결제 완료 시각(completed_at)으로, 교체 구간 안만 본다.
    if as_of is not None:
        col, w5, skip = "loaded_at", w3, _replaced_filter(query, cfg, tick)
    else:
        w5, skip = (max(w3[0], bounds[0]), min(w3[1], bounds[1])) if bounds else w3, ""
        col = "completed_at"
    dup = [] if w5[1] <= w5[0] else query(f"""SELECT t.order_id, COUNT(*) AS success_count FROM gold_b.payment_attempts t
WHERE t.status = 'SUCCESS' AND t.order_id IN (SELECT order_id FROM gold_b.payment_attempts
                                              WHERE status = 'SUCCESS' AND {_in(col, *w5, cfg)}{skip})
GROUP BY t.order_id HAVING COUNT(*) > 1""")
    out += r5_duplicate_success(cfg, run_id, now, w5, dup)
    if as_of is not None:   # R6: Silver 수동 배치 결과를 최신 상태로 읽는다. 재처리(Kafka에서 원장 재생성)와 무관해서 재판정에서는 빼고 비교에서도 뺀다
        out += _r6(query, cfg, run_id, now)
    return out


def _run_record(run_id, kind, request_id, start, end, now, count):
    f = "%Y-%m-%d %H:%M:%S"
    return {"run_id": run_id, "kind": kind, "request_id": request_id, "judged_from": start.strftime(f),
            "judged_to": end.strftime(f), "started_at": now.strftime(f), "anomaly_count": count}


def regular_run(query, write, cfg: Config, now: datetime, tick: datetime = None):
    """tick을 주면(Airflow의 논리 시각) 그 시각으로 순찰 번호를 만든다. 실패한 작업을 다시 돌려도 같은 번호가 되어 이중 저장이 안 생긴다."""
    tick = floor_tick(tick or now)
    run_id = tick.strftime("%Y%m%dT%H%MZ")
    if query(f"SELECT run_id FROM gold_b.detection_runs WHERE run_id = '{run_id}'"):
        return {"run_id": run_id, "skipped": True}          # 같은 번호를 두 번 돌리지 않는다
    rows = judge(query, cfg, tick, run_id, now, as_of=tick)
    # 이상 줄을 쓰고 순찰 기록을 쓰기 전에 멈췄다가 다시 도는 경우를 위해, 이 순찰 번호로 이미 쓴 줄은 다시 쓰지 않는다
    total = len(rows)
    done = {r["anomaly_id"] for r in query(f"SELECT anomaly_id FROM gold_b.anomaly WHERE run_id = '{run_id}'")}
    rows = [r for r in rows if r["anomaly_id"] not in done]
    if rows:
        write("anomaly", rows)
    write("detection_runs", [_run_record(run_id, "REGULAR", None, tick - timedelta(minutes=STEP_MIN), tick, now, total)])
    return {"run_id": run_id, "anomalies": total}


def _event(request_id, step, now, ws, we, detail, cfg):
    f = "%Y-%m-%d %H:%M:%S"
    return {"request_id": request_id, "step": step, "at": now.strftime(f), "actor": ACTOR, "reason": None,
            "window_start": ws, "window_end": we, "rule_version": cfg.rule_version, "source": None,
            "attempt": None, "parent_request_id": None, "detail": detail}


def pending_replacements(query):
    """LEDGER_REPLACED 줄 중, 같은 요청·같은 시간대의 REDETECTED가 아직 없는 것.

    Gold B 원장 재처리(source가 KAFKA·BRONZE)만 본다. 은서 님 poller와 같은 조건이다.
    Silver 재처리(source = 'SILVER', R6)의 교체 줄은 Gold B 규칙으로 다시 판정할 대상이 아니라서 뺀다.
    """
    return query("""SELECT l.request_id, l.window_start, l.window_end
FROM gold_b.reprocess_events l
WHERE l.step = 'LEDGER_REPLACED' AND (l.source IS NULL OR l.source IN ('KAFKA', 'BRONZE'))
  AND NOT EXISTS (SELECT 1 FROM gold_b.reprocess_events r
                  WHERE r.request_id = l.request_id AND r.step = 'REDETECTED'
                    AND r.window_start = l.window_start AND r.window_end = l.window_end)
ORDER BY l.window_start""")


def redetect(query, write, cfg: Config, now: datetime, item):
    """교체된 시간대를 5분 간격으로 다시 훑어 판정하고, 이전 판정과 비교해 해결 여부를 기록한다."""
    rid, ws, we = item["request_id"], item["window_start"], item["window_end"]
    start, end = datetime.fromisoformat(str(ws)), datetime.fromisoformat(str(we))
    run_id = f"{start:%Y%m%dT%H%MZ}-RD-{rid}"     # 요청과 교체 구간으로 정해서, 실패한 작업을 다시 돌려도 같은 번호가 된다(이중 저장 방지)
    prior_rows = query(f"""SELECT * FROM gold_b.anomaly
WHERE window_end > {_ts(start, cfg)} AND window_start < {_ts(end, cfg)} AND rule_id NOT IN ('R3_BRONZE_LAG', '{R6_RULE}')
  AND run_id <> '{run_id}'""")   # 교체된 시간대와 겹치는 옛 판정 (R3, R6은 재처리가 안 바꾸는 값이라 비교에서 뺀다. 자기 번호의 줄도 뺀다)
    key = lambda r: (r["rule_id"], r["scope_type"], r["scope_key"])   # 규칙·대상이 같으면 같은 이상 (R5는 순찰·재판정의 시간 기준이 달라 id로 비교할 수 없다)
    prior_ids = {key(r) for r in prior_rows}
    rows, tick = [], start + timedelta(minutes=STEP_MIN)
    while True:   # 정규 순찰과 같은 5분 시각으로 훑는다. 비율 규칙은 구간이 끝난 지 3분 뒤를 보므로, 교체 구간의 끝까지 덮을 때까지 한 번 더 훑는다
        rows += judge(query, cfg, tick, run_id, now, as_of=None, bounds=(start, end))
        if tick - timedelta(minutes=cfg.ratio_wait_min) >= end:
            break
        tick += timedelta(minutes=STEP_MIN)
    seen, unique = set(), []
    for r in rows:                                            # 겹치는 판정 구간의 같은 이상은 한 줄만
        if r["anomaly_id"] not in seen:
            seen.add(r["anomaly_id"]); unique.append(r)
    new_ids = {key(r) for r in unique}
    done = {r["anomaly_id"] for r in query(f"SELECT anomaly_id FROM gold_b.anomaly WHERE run_id = '{run_id}'")}   # 앞선 시도가 이미 쓴 줄은 다시 쓰지 않는다
    fresh = [r for r in unique if r["anomaly_id"] not in done]
    latest = {}                                               # 같은 이상(anomaly_id)의 가장 최근 줄 (뷰 anomaly_current와 같은 기준)
    for r in prior_rows:
        cur = latest.get(r["anomaly_id"])
        if cur is None or (str(r["detected_at"]), r["run_id"]) > (str(cur["detected_at"]), cur["run_id"]):
            latest[r["anomaly_id"]] = r
    # 재처리 뒤 사라진 이상은 RESOLVED 줄을 새로 쌓는다. 그래야 anomaly_current만 읽어도 해결된 것으로 보인다 (이미 쓴 줄은 다시 쓰지 않는다)
    resolved = [dict(r, run_id=run_id, status="RESOLVED", detected_at=now.strftime("%Y-%m-%d %H:%M:%S"),
                     evidence_ref=json.dumps({"resolved_by_request": rid, "redetect_run_id": run_id, "original_run_id": r["run_id"]}))
                for r in latest.values()
                if key(r) not in new_ids and r["status"] != "RESOLVED" and r["anomaly_id"] not in done]
    if fresh or resolved:
        write("anomaly", fresh + resolved)
    if not query(f"SELECT run_id FROM gold_b.detection_runs WHERE run_id = '{run_id}'"):
        write("detection_runs", [_run_record(run_id, "REDETECT", rid, start, end, now, len(unique))])
    remaining = prior_ids & new_ids
    result = "NO_ANOMALY_BEFORE" if not prior_ids else ("RESOLVED" if not remaining else "STILL_OPEN")
    detail = json.dumps({"before": len(prior_ids), "after": len(new_ids), "still_open": len(remaining), "result": result,
                         "excluded_rules": ["R3_BRONZE_LAG", R6_RULE]})
    write("reprocess_events", [_event(rid, "REDETECTED", now, str(ws), str(we), f"run_id={run_id}", cfg),
                               _event(rid, "VERIFIED", now, str(ws), str(we), detail, cfg)])
    return {"request_id": rid, "run_id": run_id, "result": result}


def run_once(query, write, cfg: Config = None, now: datetime = None, tick: datetime = None):
    cfg = cfg or Config()
    now = now or datetime.utcnow()
    summary = {"regular": regular_run(query, write, cfg, now, tick), "redetected": []}
    for item in pending_replacements(query):
        summary["redetected"].append(redetect(query, write, cfg, now, item))
    return summary
