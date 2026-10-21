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
  INVESTIGATE_LOOKBACK_HOURS  몇 시간 전까지의 이상을 볼지 (기본 24)
  AWS_BEARER_TOKEN_BEDROCK 선택. 내 컴퓨터에서 Bedrock API 키로 시험할 때만
쿼리 문장과 쿼리 결과는 출력하지 않는다. 결과 요약만 JSON 한 줄로 출력한다.
"""
import json
import os
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


def find_pending(query, now, limit=3, lookback_hours=24):
    """최근 이상 중 조사가 필요한 것. 해소 줄(RESOLVED)과 이미 조사한 것(오류가 한도 미만이면 다시 시도)은 뺀다."""
    since = now - timedelta(hours=lookback_hours)
    anomalies = query(f"""SELECT * FROM gold_b.anomaly_current
WHERE status = 'OPEN' AND detected_at >= {_ts(since)}
ORDER BY detected_at LIMIT 200""")
    runs = query(f"""SELECT anomaly_id, status FROM agent.investigation_runs
WHERE dt >= '{(since - timedelta(days=1)):%Y-%m-%d}' LIMIT 200""")
    done, errors = set(), {}
    for r in runs:
        if r["status"] == "ERROR":
            errors[r["anomaly_id"]] = errors.get(r["anomaly_id"], 0) + 1
        else:
            done.add(r["anomaly_id"])
    pending = [a for a in anomalies if a["anomaly_id"] not in done and errors.get(a["anomaly_id"], 0) <= MAX_ERROR_RETRIES]
    return pending[:limit]


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
    summary = {"found": len(pending), "results": results, "model_id": converse.model_id, "usage": converse.usage}
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return summary


if __name__ == "__main__":
    main()
