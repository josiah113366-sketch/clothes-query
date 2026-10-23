"""조사 실행 진입점: Airflow가 5분마다 이 파일을 한 번 실행한다 (조사 에이전트 컨테이너 이미지의 ENTRYPOINT).

한 번 실행하면
  1. 최근 이상 중 아직 조사하지 않은 것을 찾는다 (gold_b.anomaly_current의 OPEN, 조사 기록이 없는 것, 최대 INVESTIGATE_MAX개).
  2. 이상마다 조사 루프(loop.investigate)를 돌려 리포트를 만든다.
  3. 리포트(agent.investigation_reports)와 실행 기록(agent.investigation_runs)을 새 줄로 쌓는다. 오류로 끝나도 실행 기록은 남긴다.

환경 변수 (비밀값은 없다. AWS 권한은 ServiceAccount에 연결된 역할이 준다)
  ATHENA_WORKGROUP         (필수) 조사용 workgroup
  BEDROCK_MODEL_ID         (필수) 모델 ID (예: amazon.nova-lite-v1:0)
  AWS_REGION               기본 ap-northeast-1
  INVESTIGATE_MAX          한 번에 조사할 이상 수 (기본 3, 비용을 묶어 두는 상한)
  INVESTIGATE_LOOKBACK_HOURS  몇 시간 전까지의 이상을 볼지 (기본 24). 조사 DAG가 오래 멈췄다면 이 값을 늘려 한 번 돌리면 놓친 이상을 조사한다
  INVESTIGATE_MARK_EXPIRED    기본 1. 조사 기간을 넘겨 조사 못 한 OPEN 이상에 EXPIRED 기록을 남긴다(0이면 끔)
  AWS_BEARER_TOKEN_BEDROCK 선택. 내 컴퓨터에서 Bedrock API 키로 시험할 때만
쿼리 문장과 쿼리 결과는 출력하지 않는다. 결과 요약만 JSON 한 줄로 출력한다.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "detect"))
from athena_io import AthenaIO          # noqa: E402

from bedrock_io import BedrockConverse  # noqa: E402
from loop import investigate            # noqa: E402

MAX_ERROR_RETRIES = 2     # 오류로 끝난 이상은 이 횟수까지만 다시 조사한다 (임의 값)
TRACE_LIMIT = 20_000      # 조사 과정 JSON의 최대 글자 수 (Athena 쿼리 크기 한도 안에 들게)
F = "%Y-%m-%d %H:%M:%S"


def _ts(dt):
    return f"TIMESTAMP '{dt.strftime(F)}'"


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
EXPIRE_DAYS = 7           # 조사 기간(lookback)을 넘긴 미조사 이상을 EXPIRED로 표시할 때 거슬러 올라가는 기간
EXPIRE_MAX = 200          # 한 번에 표시하는 상한


def _runs_by_anomaly(query, since):
    """조사 기록을 이상별로 묶는다: (조사를 마친 이상 id 집합, 오류 횟수, 이미 EXPIRED로 표시한 id 집합)."""
    runs = query(f"""SELECT anomaly_id, status FROM agent.investigation_runs
WHERE dt >= '{(since - timedelta(days=1)):%Y-%m-%d}' LIMIT 5000""")
    done, errors, expired = set(), {}, set()
    for r in runs:
        if r["status"] == "ERROR":
            errors[r["anomaly_id"]] = errors.get(r["anomaly_id"], 0) + 1
        elif r["status"] == "EXPIRED":
            expired.add(r["anomaly_id"])      # 기간을 넘겨 건너뛴 것. 조사한 것이 아니므로 조사 기간을 늘려 다시 돌리면 조사할 수 있다
        else:
            done.add(r["anomaly_id"])
    return done, errors, expired


def find_pending(query, now, limit=3, lookback_hours=24):
    """최근 이상 중 조사가 필요한 것, 오래된 것부터. 해소 줄(RESOLVED)과 이미 조사한 것(오류가 한도 미만이면 다시 시도)은 뺀다.

    조사를 마친 이상은 상태가 OPEN으로 남으므로, 쿼리에서도 id로 빼서(NOT IN) 이미 조사한 이상이 앞을 채워 새 이상이 밀리지 않게 한다.
    """
    since = now - timedelta(hours=lookback_hours)
    done, errors, _ = _runs_by_anomaly(query, since)
    skip = sorted(i for i in (done | {k for k, n in errors.items() if n > MAX_ERROR_RETRIES}) if _SAFE_ID.match(str(i)))
    exclude = f"AND anomaly_id NOT IN ({', '.join(repr(i) for i in skip)})" if skip else ""
    anomalies = query(f"""SELECT * FROM gold_b.anomaly_current
WHERE status = 'OPEN' AND detected_at >= {_ts(since)} {exclude}
ORDER BY detected_at LIMIT {int(limit) + 10}""")
    pending = [a for a in anomalies if a["anomaly_id"] not in done and errors.get(a["anomaly_id"], 0) <= MAX_ERROR_RETRIES]
    return pending[:limit]


def mark_expired(query, write, now, lookback_hours=24):
    """조사 기간을 넘겨(기본 24시간) 조사하지 못한 OPEN 이상에 실행 기록(EXPIRED)을 한 줄 남긴다. 조용히 사라지지 않고 대시보드에서 보이게 하려는 것이다.
    조사 DAG가 오래 멈췄다가 살아났을 때 놓친 이상을 찾는 용도다. 다시 조사하려면 INVESTIGATE_LOOKBACK_HOURS를 늘려 한 번 돌린다."""
    since = now - timedelta(hours=lookback_hours)
    seen = query(f"""SELECT anomaly_id, status FROM agent.investigation_runs
WHERE dt >= '{(since - timedelta(days=EXPIRE_DAYS + 1)):%Y-%m-%d}' LIMIT 5000""")
    skip = sorted({r["anomaly_id"] for r in seen if _SAFE_ID.match(str(r["anomaly_id"]))})
    exclude = f"AND anomaly_id NOT IN ({', '.join(repr(i) for i in skip)})" if skip else ""
    old = query(f"""SELECT anomaly_id FROM gold_b.anomaly_current
WHERE status = 'OPEN' AND detected_at < {_ts(since)} AND detected_at >= {_ts(since - timedelta(days=EXPIRE_DAYS))} {exclude}
ORDER BY detected_at LIMIT {EXPIRE_MAX}""")
    old = [a for a in old if a["anomaly_id"] not in set(skip)]
    rows = [{"run_id": f"exp-{now:%Y%m%dT%H%M%S}-{str(a['anomaly_id'])[-8:]}", "anomaly_id": a["anomaly_id"], "started_at": now, "finished_at": now,
             "status": "EXPIRED", "error": f"조사 기간({lookback_hours}시간)을 넘겨 조사하지 않았습니다"} for a in old]
    if rows:
        write("investigation_runs", rows)
    return len(rows)


def _status(report):
    if report["cause_layer"] == "UNKNOWN" and not report.get("claims"):
        return "UNKNOWN"
    return "INCOMPLETE" if report.get("problems") else "REPORTED"


def _short(text, n=200):
    return str(text).replace("\n", " ")[:n]


def run_one(anomaly, query, write, converse, now_fn):
    started = now_fn()
    run_id = f"inv-{started:%Y%m%dT%H%M%S}-{str(anomaly['anomaly_id'])[-8:]}"
    before = dict(converse.usage)
    row = {"run_id": run_id, "anomaly_id": anomaly["anomaly_id"], "started_at": started, "model_id": converse.model_id}
    try:
        report = investigate(anomaly, converse, query, dialect="athena", now=started)
    except Exception as e:     # 모델·Athena 오류 등. 실행 기록에는 오류 종류와 짧은 메시지만 남긴다
        row.update(finished_at=now_fn(), status="ERROR", turns=converse.usage["calls"] - before["calls"], error=_short(f"{type(e).__name__}: {e}"))
        write("investigation_runs", [row])
        return {"anomaly_id": anomaly["anomaly_id"], "status": "ERROR"}
    finished = now_fn()
    trace = report.get("trace", [])
    trace_json = json.dumps(trace, ensure_ascii=False, default=str)
    if len(trace_json) > TRACE_LIMIT:
        trace_json = json.dumps([{"tool": t.get("tool"), "status": t.get("status")} for t in trace], ensure_ascii=False)
    write("investigation_reports", [{
        "report_id": report["report_id"], "anomaly_id": report["anomaly_id"], "investigation_run_id": run_id, "created_at": finished,
        "cause_layer": report["cause_layer"], "conclusion": report["conclusion"],
        "claims": json.dumps(report.get("claims", []), ensure_ascii=False), "trace": trace_json,
        "problems": json.dumps(report["problems"], ensure_ascii=False) if report.get("problems") else None, "model_id": converse.model_id}])
    status = _status(report)
    row.update(finished_at=finished, status=status, report_id=report["report_id"], cause_layer=report["cause_layer"],
               turns=converse.usage["calls"] - before["calls"], tool_calls=sum(1 for t in trace if t.get("status") == "ok" and t.get("tool") != "submit_report"),
               rejected_submissions=sum(1 for t in trace if t.get("status") == "rejected"))
    write("investigation_runs", [row])
    return {"anomaly_id": anomaly["anomaly_id"], "status": status, "report_id": report["report_id"]}


def main(env=None, io=None, converse=None, now_fn=None):
    env = os.environ if env is None else env
    now_fn = now_fn or (lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    if io is None:
        if not env.get("ATHENA_WORKGROUP"):
            sys.exit("ATHENA_WORKGROUP 환경 변수가 필요합니다.")
        io = AthenaIO(env["ATHENA_WORKGROUP"], env.get("ATHENA_DATABASE", "gold_b"), region=env.get("AWS_REGION"))
    if converse is None:
        converse = BedrockConverse.from_env(env)
    pending = find_pending(io.query, now_fn(), int(env.get("INVESTIGATE_MAX", 3)), int(env.get("INVESTIGATE_LOOKBACK_HOURS", 24)))
    results = [run_one(a, io.query, io.write, converse, now_fn) for a in pending]
    lookback = int(env.get("INVESTIGATE_LOOKBACK_HOURS", 24))
    expired = mark_expired(io.query, io.write, now_fn(), lookback) if env.get("INVESTIGATE_MARK_EXPIRED", "1") == "1" else 0
    errors = sum(1 for r in results if r["status"] == "ERROR")
    summary = {"found": len(pending), "errors": errors, "results": results, "expired_marked": expired, "model_id": converse.model_id, "usage": converse.usage}
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return summary


def exit_code(summary):
    """종료 코드 기준: 조사 대상이 있는데 전부 ERROR면 실패(1), 그 밖에는 성공(0).
    일부만 ERROR면 성공으로 끝낸다. 실패한 이상은 실행 기록에 ERROR로 남아 다음 5분 순찰에서 다시 조사하고(최대 MAX_ERROR_RETRIES회),
    성공한 이상의 리포트는 이미 저장돼 있다. 일부 실패 때문에 작업 전체를 실패로 돌려 재시도하면 같은 일을 또 하게 된다.
    일부 실패 건수는 요약의 errors로 본다."""
    return 1 if summary["found"] and summary["errors"] == summary["found"] else 0


if __name__ == "__main__":
    code = exit_code(main())
    if code:
        print("조사 대상이 있었지만 모두 ERROR로 끝났습니다.", file=sys.stderr)
    sys.exit(code)
