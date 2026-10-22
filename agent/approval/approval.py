"""재처리 승인의 백엔드 규칙: 요청 → 승인/거절 → Airflow DAG 호출. 화면(대시보드)은 이 함수들을 부르기만 한다.

왜 따로 두나: 인프라는 "reprocess_events에 쓸 수 있다"까지만 막을 수 있고, 어떤 단계의 줄을 쓸 수 있는지(REQUESTED/APPROVED만),
누가 승인했는지, 같은 요청을 두 번 승인하지 않는지는 IAM으로 막을 수 없다(인프라 담당 답변). 그 검사를 이 파일이 맡는다.
Streamlit을 불러오지 않아서 일반 파이썬으로 시험한다. 실제 Athena는 query/write 함수로, Airflow는 trigger 함수로 주입한다.

단계(step) 흐름 (reprocess_events)
  REQUESTED -> APPROVED | REJECTED            (이 파일이 쓴다: 사람이 화면에서)
  APPROVED  -> STARTED -> LEDGER_REPLACED ... (재처리 DAG가 쓴다)
  -> REDETECTED -> VERIFIED                   (판정 잡이 쓴다)
"""
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

STEP_ORDER = ("REQUESTED", "APPROVED", "REJECTED", "STARTED", "LEDGER_REPLACED", "FAILED", "REDETECTED", "VERIFIED")
TERMINAL = ("REJECTED", "VERIFIED")
FMT = "%Y-%m-%d %H:%M:%S"
_ID = re.compile(r"^[A-Za-z0-9._:+-]{1,100}$")      # Airflow의 dag_run_id로도 쓰이므로 안전한 글자만


@dataclass
class ApprovalConfig:
    ttl_minutes: int = 60                 # 요청 후 승인, 승인 후 시작까지 허용하는 시간 (제안 값, 팀 이의 기한 중)
    max_attempts: int = 2                 # 재시도 최대 횟수 (은서 님 동의)
    rule_version: str = "0.1.0"           # 공통 형식 검사 규칙 버전
    dialect: str = "athena"               # 시험에서만 "sqlite"
    # 규칙 -> (호출할 DAG ID, source). DAG ID가 None이면 아직 정해지지 않은 것. R3는 재처리가 값을 바꾸지 않아 대상이 아니다
    dag_by_rule: dict = field(default_factory=lambda: {
        "R6_ORDER_TOTAL_MISMATCH": ("silver_gold_a_reprocess", "SILVER"),     # 현지 님 제안 이름(아직 확정 아님)
        "R1_PG_FAILURES": (None, "KAFKA"), "R4_MALFORMED": (None, "KAFKA"), "R5_DUPLICATE_SUCCESS": (None, "KAFKA"),   # Gold B 재처리 DAG ID 대기(은서 님)
    })
    # 재처리해도 원본이 안 바뀌어 해결되지 않을 수 있는 규칙(화면에 경고를 띄운다)
    unfixable_by_reprocess: tuple = ("R5_DUPLICATE_SUCCESS", "R6_ORDER_TOTAL_MISMATCH")


class ApprovalError(Exception):
    """사람에게 보여 줄 수 있는 거절 이유. code는 화면이 분기에 쓴다."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _parse(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("T", " ")[:19])


def _check_id(value, what):
    if not _ID.match(str(value or "")):
        raise ApprovalError("BAD_ID", f"{what} 형식이 올바르지 않습니다.")
    return str(value)


def _ts(text, cfg):
    return f"'{text}'" if cfg.dialect == "sqlite" else f"TIMESTAMP '{text}'"


def check_actor(actor):
    """승인자는 로그인한 사용자의 신원(이메일)이어야 한다. 화면 입력값이나 개발용 사용자는 받지 않는다."""
    actor = str(actor or "").strip()
    if not actor or actor.lower() in ("dev-user", "unknown", "anonymous") or "@" not in actor:
        raise ApprovalError("ACTOR_REQUIRED", "로그인한 사용자 이메일이 필요합니다(개발용 로그인으로는 승인할 수 없습니다).")
    return actor


def fetch_rows(query, request_id):
    _check_id(request_id, "request_id")
    return query(f"SELECT * FROM gold_b.reprocess_events WHERE request_id = '{request_id}' ORDER BY at")


def latest_row(rows):
    """같은 시각에 두 줄이 찍힐 수 있으므로 시각, 단계 순서로 가장 최근 줄을 고른다."""
    order = {s: i for i, s in enumerate(STEP_ORDER)}
    return max(rows, key=lambda r: (_parse(r["at"]), order.get(r["step"], -1))) if rows else None


def derive_state(rows, now, cfg=ApprovalConfig()):
    """요청의 현재 상태. 만료는 줄이 아니라 시각으로 계산한다(EXPIRED_REQUEST, EXPIRED_APPROVAL)."""
    last = latest_row(rows)
    if last is None:
        return None
    ttl = timedelta(minutes=cfg.ttl_minutes)
    if last["step"] == "REQUESTED" and now - _parse(last["at"]) > ttl:
        return "EXPIRED_REQUEST"
    if last["step"] == "APPROVED" and now - _parse(last["at"]) > ttl:
        return "EXPIRED_APPROVAL"
    return last["step"]


def _detail(row):
    try:
        return json.loads(row.get("detail") or "{}")
    except ValueError:
        return {}


def _event(base, step, actor, now, reason=None, extra=None):
    detail = dict(_detail(base), **(extra or {}))
    return {"request_id": base["request_id"], "step": step, "at": now.strftime(FMT), "actor": actor, "reason": reason,
            "window_start": base["window_start"], "window_end": base["window_end"], "rule_version": base["rule_version"],
            "source": base["source"], "attempt": base["attempt"], "parent_request_id": base["parent_request_id"],
            "detail": json.dumps(detail, ensure_ascii=False)}


def _hours(start, end, source):
    """Gold B 원장(KAFKA)은 1시간 폴더 단위로 교체하므로 이상의 시간대를 정시로 넓힌다. Silver는 그대로."""
    if source != "KAFKA":
        return start, end
    s = start.replace(minute=0, second=0, microsecond=0)
    e = end if end == end.replace(minute=0, second=0, microsecond=0) else end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return s, e


def request_reprocess(anomaly, report_id, actor, now, query, write, cfg=ApprovalConfig(), attempt=1, parent_request_id=None):
    """이상 하나에 대한 재처리를 요청한다(REQUESTED 줄). anomaly는 anomaly_current의 한 줄(딕셔너리)."""
    actor = check_actor(actor)
    rule = anomaly.get("rule_id")
    if rule not in cfg.dag_by_rule:
        raise ApprovalError("NOT_REPROCESSABLE", f"{rule}는 재처리 대상이 아닙니다(재처리가 값을 바꾸지 않는 규칙).")
    dag_id, source = cfg.dag_by_rule[rule]
    if not dag_id:
        raise ApprovalError("DAG_NOT_CONFIGURED", f"{rule}에 연결된 재처리 DAG가 아직 정해지지 않았습니다.")
    anomaly_id = _check_id(anomaly.get("anomaly_id"), "anomaly_id")
    if attempt > cfg.max_attempts + 1:
        raise ApprovalError("TOO_MANY_ATTEMPTS", f"재시도는 최대 {cfg.max_attempts}번입니다.")
    since = (now - timedelta(hours=6)).strftime(FMT)
    for row in query(f"SELECT request_id FROM gold_b.reprocess_events WHERE step = 'REQUESTED' AND at >= {_ts(since, cfg)} "
                     f"AND detail LIKE '%\"anomaly_id\": \"{anomaly_id}\"%'"):
        state = derive_state(fetch_rows(query, row["request_id"]), now, cfg)
        if state not in TERMINAL and state not in ("EXPIRED_REQUEST", "EXPIRED_APPROVAL", "FAILED"):
            raise ApprovalError("DUPLICATE_REQUEST", f"이미 진행 중인 요청({row['request_id']})이 있습니다.")
    start, end = _hours(_parse(anomaly["window_start"]), _parse(anomaly["window_end"]), source)
    request_id = f"rq-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    detail = {"anomaly_id": anomaly_id, "report_id": report_id, "rule_id": rule, "dag_id": dag_id}
    if rule == "R6_ORDER_TOTAL_MISMATCH":
        try:
            detail["order_ids"] = json.loads(anomaly.get("evidence_ref") or "{}").get("new_orders", [])[:500]
        except ValueError:
            detail["order_ids"] = []
    row = {"request_id": request_id, "step": "REQUESTED", "at": now.strftime(FMT), "actor": actor, "reason": None,
           "window_start": start.strftime(FMT), "window_end": end.strftime(FMT), "rule_version": cfg.rule_version, "source": source,
           "attempt": attempt, "parent_request_id": parent_request_id, "detail": json.dumps(detail, ensure_ascii=False)}
    write("reprocess_events", [row])
    return {"request_id": request_id, "state": "REQUESTED", "warning": "UNFIXABLE_BY_REPROCESS" if rule in cfg.unfixable_by_reprocess else None}


def reject(request_id, actor, reason, now, query, write, cfg=ApprovalConfig()):
    actor = check_actor(actor)
    rows = fetch_rows(query, request_id)
    state = derive_state(rows, now, cfg)
    if state != "REQUESTED":
        raise ApprovalError("BAD_STATE", f"거절할 수 없는 상태입니다: {state or '요청 없음'}")
    write("reprocess_events", [_event(latest_row(rows), "REJECTED", actor, now, reason=(reason or None))])
    return {"request_id": request_id, "state": "REJECTED"}


def approve(request_id, actor, now, query, write, trigger, cfg=ApprovalConfig()):
    """승인하고 곧바로 DAG를 호출한다. 이미 승인된 요청이면 승인 줄을 다시 쓰지 않고 호출만 다시 시도한다."""
    actor = check_actor(actor)
    rows = fetch_rows(query, request_id)
    state = derive_state(rows, now, cfg)
    if state == "REQUESTED":
        write("reprocess_events", [_event(latest_row(rows), "APPROVED", actor, now, extra={"approved_by": actor})])
    elif state != "APPROVED":
        raise ApprovalError("BAD_STATE", {"EXPIRED_REQUEST": "요청이 만료됐습니다. 새로 요청하세요.", "EXPIRED_APPROVAL": "승인이 만료됐습니다. 새로 요청하세요.",
                                          None: "요청이 없습니다."}.get(state, f"승인할 수 없는 상태입니다: {state}"))
    return start_run(request_id, now, query, trigger, cfg)


def start_run(request_id, now, query, trigger, cfg=ApprovalConfig()):
    """Airflow DAG를 부른다. dag_run_id를 request_id로 하므로 같은 요청을 두 번 불러도 Airflow가 409로 막는다(성공으로 본다)."""
    rows = fetch_rows(query, request_id)
    state = derive_state(rows, now, cfg)
    if state != "APPROVED":
        raise ApprovalError("BAD_STATE", f"시작할 수 없는 상태입니다: {state or '요청 없음'}")
    base = latest_row(rows)
    detail = _detail(base)
    req = next((r for r in rows if r["step"] == "REQUESTED"), None)
    if req is None:
        raise ApprovalError("BAD_STATE", "요청 줄(REQUESTED)이 없습니다.")
    conf = {"request_id": request_id, "window_start": base["window_start"], "window_end": base["window_end"], "rule_version": base["rule_version"],
            "source": base["source"], "anomaly_id": detail.get("anomaly_id"), "report_id": detail.get("report_id"), "attempt": base["attempt"]}
    if "order_ids" in _detail(req):
        conf["order_ids"] = _detail(req)["order_ids"]
    status = trigger(detail["dag_id"], request_id, conf)
    if status in (200, 201):
        return {"request_id": request_id, "state": "APPROVED", "airflow": "TRIGGERED"}
    if status == 409:
        return {"request_id": request_id, "state": "APPROVED", "airflow": "ALREADY_TRIGGERED"}
    raise ApprovalError("AIRFLOW_FAILED", f"Airflow 호출이 실패했습니다(상태 {status}). 같은 승인으로 다시 시도할 수 있습니다.")


class AirflowClient:
    """Airflow 3 REST API: POST /auth/token 으로 토큰을 받고 POST /api/v2/dags/{dag_id}/dagRuns 로 DAG를 부른다.
    접속 정보는 인자로 받는다(호출하는 쪽이 Kubernetes Secret에서 읽는다). 오류 글에 비밀번호·토큰·응답 본문을 넣지 않는다."""

    def __init__(self, base_url, username, password, opener=urllib.request.urlopen, timeout=15):
        self.base_url, self._username, self._password, self._open, self.timeout = base_url.rstrip("/"), username, password, opener, timeout

    def _post(self, path, body, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as error:
            return error.code, b""
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, b""

    def trigger(self, dag_id, dag_run_id, conf):
        _check_id(dag_id, "dag_id")
        _check_id(dag_run_id, "dag_run_id")
        status, raw = self._post("/auth/token", {"username": self._username, "password": self._password})
        if status not in (200, 201):
            return status or 0
        try:
            token = json.loads(raw)["access_token"]
        except (ValueError, KeyError, TypeError):
            return 0
        status, _ = self._post(f"/api/v2/dags/{dag_id}/dagRuns", {"logical_date": None, "dag_run_id": dag_run_id, "conf": conf}, token)
        return status
