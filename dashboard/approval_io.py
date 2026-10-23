"""[데이터 관리] 재처리 승인 화면이 쓰는 연결과 조회. 화면 파일(pages_data/approval.py)은 이 모듈만 부른다.

승인 규칙(누가, 어떤 상태에서, 중복 승인은 막는지)은 `agent/approval/approval.py`가 맡는다. 이 모듈은
  1) 그 코드와 Athena 연결 코드(`agent/detect/athena_io.py`)를 찾아 불러오고,
  2) 환경에 맞는 저장소(query/write)와 Airflow 호출기를 만들고,
  3) 화면에 보여줄 목록(승인할 이상, 요청 현황, 조사 리포트)을 읽는다.

두 가지 모드
  REAL     환경변수 APPROVAL_ATHENA_WORKGROUP이 있을 때. 진짜 Athena에 읽고 쓰고, 승인하면 Airflow API를 부른다.
  PRACTICE 환경변수가 없을 때(내 PC). 메모리 안의 가짜 저장소와 가짜 Airflow로 화면만 연습한다. 아무것도 바깥에 쓰지 않는다.

환경변수 (비밀값은 Kubernetes Secret에서 주입한다. 코드·Git에 넣지 않는다)
  APPROVAL_ATHENA_WORKGROUP, AWS_REGION            Athena (대시보드 전용 workgroup)
  AIRFLOW_API_URL, AIRFLOW_API_USER, AIRFLOW_API_PASSWORD   Airflow API (DAG를 직접 부르는 규칙 R6용)
  AGENT_CODE_DIR                                    agent 폴더 위치 (이미지에 복사했을 때. 기본은 저장소의 agent/)
"""
import importlib.util
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

FMT = "%Y-%m-%d %H:%M:%S"
CANDIDATE_STATUSES = ("OPEN", "INVESTIGATING", "REPORTED")   # 아직 해결·만료되지 않은 이상 (anomaly_current.status)
CANDIDATE_HOURS = 48       # 승인 후보로 보는 이상의 나이 (임의 값)
REQUEST_HOURS = 24         # 요청 현황으로 보는 기간 (임의 값. 승인 유효 시간 60분보다 충분히 길다)
PRACTICE_ACTOR = "practice@example.com"


def _agent_dir() -> Path:
    return Path(os.getenv("AGENT_CODE_DIR") or Path(__file__).resolve().parents[1] / "agent")


def _load(alias: str, path: Path):
    """파일 경로로 모듈을 불러온다. 이름이 겹치는 모듈(approval 등)과 섞이지 않게 별칭으로 등록한다."""
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


ap = _load("agent_approval", _agent_dir() / "approval" / "approval.py")
ApprovalError, ApprovalConfig = ap.ApprovalError, ap.ApprovalConfig


@dataclass
class Backend:
    mode: str                     # "REAL" | "PRACTICE"
    query: Callable               # query(sql) -> 줄 목록(dict)
    write: Callable               # write(표, 줄 목록)
    trigger: Callable             # trigger(dag_id, dag_run_id, conf) -> HTTP 상태
    cfg: "ApprovalConfig"


# ---------- 연습용 가짜 저장소 ----------

def _practice_backend(now: datetime) -> Backend:
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ':memory:' AS gold_b")
    con.execute("ATTACH DATABASE ':memory:' AS agent")
    con.execute("CREATE TABLE gold_b.reprocess_events (request_id, step, at, actor, reason, window_start, window_end, rule_version, source, attempt, parent_request_id, detail)")
    con.execute("CREATE TABLE gold_b.anomaly_current (anomaly_id, rule_id, anomaly_type, scope_type, scope_key, window_start, window_end, metric, observed_value, baseline_value, status, detected_at, evidence_ref)")
    con.execute("CREATE TABLE agent.investigation_reports (report_id, anomaly_id, investigation_run_id, created_at, cause_layer, conclusion, claims, trace, problems, model_id)")

    def t(minutes_ago):
        return (now - timedelta(minutes=minutes_ago)).strftime(FMT)

    rows = [
        ("a-practice-r1", "R1_PG_FAILURES", "PG_FAILURE_SPIKE", "pg", "PG_A", t(40), t(25), "pg_cause_failure_rate", 0.85, 0.2, "REPORTED", t(22), "{}"),
        ("a-practice-r6", "R6_ORDER_TOTAL_MISMATCH", "ORDER_TOTAL_MISMATCH", "table", "silver_order_amount", t(60), t(30), "mismatch_orders", 30, 0, "REPORTED", t(20),
         json.dumps({"new_orders": ["order-0001", "order-0002"]})),
        ("a-practice-r3", "R3_BRONZE_LAG", "BRONZE_LAG_SPIKE", "topic", "payments", t(15), t(10), "bronze_lag_sec", 1500, 1200, "OPEN", t(8), "{}"),
    ]
    con.executemany("INSERT INTO gold_b.anomaly_current VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    claims = [{"text": "PG_A 결제 시도의 85%가 PG 원인으로 실패했습니다.", "kind": "FACT", "evidence": [{"tool": "payment_summary"}]},
              {"text": "PG_A 쪽 일시 장애로 보입니다.", "kind": "ASSUMPTION", "evidence": []}]
    con.execute("INSERT INTO agent.investigation_reports VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("rep-practice-1", "a-practice-r1", "inv-practice", t(18), "PAYMENT", "PG_A 장애가 원인입니다(연습용 가짜 리포트).",
                 json.dumps(claims, ensure_ascii=False), "[]", None, "practice-model"))
    con.execute("INSERT INTO agent.investigation_reports VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("rep-practice-2", "a-practice-r6", "inv-practice", t(15), "DATA_QUALITY", "[검증 미통과 · 모델이 낸 원인 층: DATA_QUALITY] 주문 총액이 품목 합계보다 큽니다(연습용).",
                 json.dumps([{"text": "30건 모두 +10,000원 불일치입니다.", "kind": "FACT", "evidence": [{"tool": "duplicate_success_orders"}]}], ensure_ascii=False),
                 "[]", json.dumps(["연습용: 검증 문제 예시"], ensure_ascii=False), "practice-model"))

    def query(sql):
        return [dict(r) for r in con.execute(sql).fetchall()]

    def write(table, new_rows):
        db = "agent" if table.startswith("investigation_") else "gold_b"
        for r in new_rows:
            cols = list(r)
            con.execute(f"INSERT INTO {db}.{table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols])

    return Backend("PRACTICE", query, write, lambda dag_id, run_id, conf: 200, ApprovalConfig(dialect="sqlite"))


def make_backend(env=None, now=None) -> Backend:
    env = os.environ if env is None else env
    workgroup = env.get("APPROVAL_ATHENA_WORKGROUP")
    if not workgroup:
        return _practice_backend(now or datetime.utcnow().replace(microsecond=0))
    athena = _load("agent_athena_io", _agent_dir() / "detect" / "athena_io.py")
    io = athena.AthenaIO(workgroup, "gold_b", region=env.get("AWS_REGION"))
    if env.get("AIRFLOW_API_URL") and env.get("AIRFLOW_API_USER") and env.get("AIRFLOW_API_PASSWORD"):
        trigger = ap.AirflowClient(env["AIRFLOW_API_URL"], env["AIRFLOW_API_USER"], env["AIRFLOW_API_PASSWORD"]).trigger
    else:
        def trigger(dag_id, dag_run_id, conf):     # Airflow 접속 정보가 없으면 호출하지 않고 실패로 돌려, 승인 줄만 남고 다시 시도할 수 있게 한다
            return 0
    return Backend("REAL", io.query, io.write, trigger, ApprovalConfig())


# ---------- 화면에 보여줄 목록 ----------

def _ts(value: datetime, cfg) -> str:
    text = value.strftime(FMT)
    return f"'{text}'" if cfg.dialect == "sqlite" else f"TIMESTAMP '{text}'"


def load_candidates(b: Backend, now: datetime) -> list:
    """승인 요청을 낼 수 있는 이상. 재처리 대상 규칙이 아니면 reprocessable=False로 표시한다(화면에서 요청 버튼을 막는다)."""
    since = now - timedelta(hours=CANDIDATE_HOURS)
    statuses = ", ".join(f"'{s}'" for s in CANDIDATE_STATUSES)
    rows = b.query(f"""SELECT anomaly_id, rule_id, anomaly_type, scope_type, scope_key, window_start, window_end, metric,
       observed_value, baseline_value, status, detected_at, evidence_ref
FROM gold_b.anomaly_current
WHERE status IN ({statuses}) AND detected_at >= {_ts(since, b.cfg)}
ORDER BY detected_at DESC
LIMIT 50""")
    for r in rows:
        dag = b.cfg.dag_by_rule.get(r["rule_id"])
        r["reprocessable"] = bool(dag and dag[0])
    return rows


def load_report(b: Backend, anomaly_id: str):
    """이상의 가장 최근 조사 리포트 한 건. 없으면 None."""
    ap._check_id(anomaly_id, "anomaly_id")
    rows = b.query(f"""SELECT report_id, created_at, cause_layer, conclusion, claims, problems, model_id
FROM agent.investigation_reports WHERE anomaly_id = '{anomaly_id}' ORDER BY created_at DESC LIMIT 1""")
    if not rows:
        return None
    r = rows[0]
    for key in ("claims", "problems"):
        try:
            r[key] = json.loads(r.get(key) or "[]")
        except ValueError:
            r[key] = []
    return r


def load_requests(b: Backend, now: datetime) -> list:
    """최근 요청별 현재 상태. 상태 = 그 요청의 마지막 줄의 단계(만료는 시각으로 계산). 최근 요청이 먼저."""
    since = now - timedelta(hours=REQUEST_HOURS)
    rows = b.query(f"SELECT * FROM gold_b.reprocess_events WHERE at >= {_ts(since, b.cfg)} ORDER BY at")
    by_request = {}
    for r in rows:
        by_request.setdefault(r["request_id"], []).append(r)
    out = []
    for rid, items in by_request.items():
        first = next((x for x in items if x["step"] == "REQUESTED"), items[0])
        last = ap.latest_row(items)
        detail = ap._detail(first)
        state = ap.derive_state(items, now, b.cfg)
        warnings = []
        if detail.get("rule_id") in b.cfg.unfixable_by_reprocess:
            warnings.append("UNFIXABLE_BY_REPROCESS")
        if first["source"] == "KAFKA" and ap._parse(first["window_start"]) < now - timedelta(days=b.cfg.kafka_retention_days):
            warnings.append("OUTSIDE_KAFKA_RETENTION")
        out.append({"request_id": rid, "state": state, "requested_at": first["at"], "last_at": last["at"], "actor": first["actor"],
                    "rule_id": detail.get("rule_id"), "anomaly_id": detail.get("anomaly_id"), "report_id": detail.get("report_id"),
                    "window_start": first["window_start"], "window_end": first["window_end"], "source": first["source"],
                    "attempt": first["attempt"], "warnings": warnings})
    return sorted(out, key=lambda x: str(x["requested_at"]), reverse=True)
