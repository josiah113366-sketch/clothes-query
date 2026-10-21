"""Athena 연결: 판정 잡이 바깥 세상과 만나는 두 함수 `query(sql)`, `write(표, 줄)`을 진짜로 만든다.

  query(sql)       -> 줄 목록(dict). Athena에 쿼리를 보내고 끝날 때까지 기다린 뒤 결과를 타입에 맞게 바꿔 돌려준다.
  write(표, 줄 목록) -> Athena `INSERT INTO`로 새 줄을 추가한다. 허용된 표(TABLE_SPECS)만 쓴다.

boto3 클라이언트는 밖에서 넣을 수 있다(`client=`). 시험은 가짜 클라이언트로 하고, 진짜 Athena에서는 아직 돌려 보지 않았다.
결과 저장 위치는 workgroup 설정이 정한다(코드에 경로를 적지 않는다).
"""
import time
from datetime import datetime

# 쓸 수 있는 표와 컬럼 타입. 표 정의(DDL)는 agent/ddl/*.sql이고, 이 목록과 같은지 agent/ddl/test_ddl.py가 확인한다.
#   database: 표가 있는 Glue 데이터베이스 (조사 에이전트 표는 gold_b 밖의 agent)
#   partitions: 파티션 컬럼 이름 (dt = 날짜, hour = 시). 값은 partition_by 시각 컬럼(UTC)에서 만든다. 파티션이 없으면 빈 목록
TABLE_SPECS = {
    "anomaly": {
        "database": "gold_b",
        "columns": {"run_id": "string", "anomaly_id": "string", "rule_id": "string", "rule_version": "string", "anomaly_type": "string",
                    "source_table": "string", "window_start": "timestamp", "window_end": "timestamp", "scope_type": "string",
                    "scope_key": "string", "metric": "string", "observed_value": "double", "baseline_value": "double",
                    "baseline_kind": "string", "sample_size": "bigint", "episode_start": "timestamp", "episode_end": "timestamp",
                    "evidence_ref": "string", "status": "string", "detected_at": "timestamp"},
        "partition_by": "detected_at", "partitions": ("dt",),
    },
    "detection_runs": {
        "database": "gold_b",
        "columns": {"run_id": "string", "kind": "string", "request_id": "string", "judged_from": "timestamp", "judged_to": "timestamp",
                    "started_at": "timestamp", "anomaly_count": "bigint"},
        "partition_by": "started_at", "partitions": ("dt",),
    },
    "reprocess_events": {     # 은서 님 DDL(양이 적어 시간 폴더 없음)과 같다. 이 잡이 쓰는 줄은 REDETECTED, VERIFIED
        "database": "gold_b",
        "columns": {"request_id": "string", "step": "string", "at": "timestamp", "actor": "string", "reason": "string",
                    "window_start": "timestamp", "window_end": "timestamp", "rule_version": "string", "source": "string",
                    "attempt": "bigint", "parent_request_id": "string", "detail": "string"},
        "partition_by": None, "partitions": (),
    },
    # 아래 둘은 조사 에이전트가 쓴다 (판정 잡 역할은 못 쓴다. 쓰는 쪽 코드는 조사 에이전트 진입점에서 연결)
    "investigation_reports": {
        "database": "agent",
        "columns": {"report_id": "string", "anomaly_id": "string", "investigation_run_id": "string", "created_at": "timestamp",
                    "cause_layer": "string", "conclusion": "string", "claims": "string", "trace": "string", "problems": "string",
                    "model_id": "string"},
        "partition_by": "created_at", "partitions": ("dt",),
    },
    "investigation_runs": {
        "database": "agent",
        "columns": {"run_id": "string", "anomaly_id": "string", "started_at": "timestamp", "finished_at": "timestamp", "status": "string",
                    "report_id": "string", "cause_layer": "string", "turns": "bigint", "tool_calls": "bigint",
                    "rejected_submissions": "bigint", "model_id": "string", "error": "string"},
        "partition_by": "started_at", "partitions": ("dt",),
    },
}
MAX_QUERY_BYTES = 200_000      # Athena 쿼리 문자열 한도(256KB)보다 낮게 잡은 한 번에 보내는 INSERT의 크기 (임의 값)
POLL_SECONDS = 1.0
TIMEOUT_SECONDS = 120.0        # 쿼리 하나를 기다리는 최대 시간 (임의 값)

_INT = {"tinyint", "smallint", "integer", "int", "bigint"}
_FLOAT = {"double", "float", "real", "decimal"}


class AthenaError(RuntimeError):
    """쿼리가 실패했거나 시간 안에 끝나지 않았다. 쿼리 내용과 결과 값은 메시지에 싣지 않는다."""


def _convert(value, type_name):
    if value is None:
        return None
    t = (type_name or "").lower()
    if t in _INT:
        return int(value)
    if t in _FLOAT or t.startswith("decimal"):
        return float(value)
    if t == "boolean":
        return value.lower() == "true"
    return value


class AthenaIO:
    def __init__(self, workgroup, database="gold_b", client=None, region=None, sleep=time.sleep, now=time.monotonic):
        self.workgroup, self.database = workgroup, database
        self._client, self._region, self._sleep, self._now = client, region, sleep, now

    def _get_client(self):
        if self._client is None:
            import boto3     # 서버에서만 필요하다. 시험은 가짜 클라이언트를 넣는다

            self._client = boto3.client("athena", region_name=self._region)
        return self._client

    def _run(self, sql):
        """쿼리를 보내고 끝날 때까지 기다려 실행 번호를 돌려준다."""
        c = self._get_client()
        qid = c.start_query_execution(QueryString=sql, WorkGroup=self.workgroup,
                                      QueryExecutionContext={"Database": self.database})["QueryExecutionId"]
        start = self._now()
        while True:
            st = c.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            state = st["State"]
            if state == "SUCCEEDED":
                return qid
            if state in ("FAILED", "CANCELLED"):
                raise AthenaError(f"Athena 쿼리가 {state} 상태로 끝났습니다 ({qid}): {st.get('StateChangeReason', '이유 없음')}")
            if self._now() - start > TIMEOUT_SECONDS:
                try:
                    c.stop_query_execution(QueryExecutionId=qid)
                except Exception:      # 멈추지 못해도 시간 초과 오류는 그대로 올린다
                    pass
                raise AthenaError(f"Athena 쿼리가 {TIMEOUT_SECONDS:.0f}초 안에 끝나지 않았습니다 ({qid})")
            self._sleep(POLL_SECONDS)

    def query(self, sql):
        qid = self._run(sql)
        c = self._get_client()
        rows, names, types, token, first = [], None, None, None, True
        while True:
            kw = {"QueryExecutionId": qid, **({"NextToken": token} if token else {})}
            page = c.get_query_results(**kw)
            meta = page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            if names is None:
                names, types = [m["Name"] for m in meta], [m["Type"] for m in meta]
            for r in page["ResultSet"]["Rows"]:
                if first:          # 첫 줄은 컬럼 이름이다
                    first = False
                    continue
                vals = [d.get("VarCharValue") for d in r["Data"]]
                rows.append({n: _convert(v, t) for n, v, t in zip(names, vals, types)})
            token = page.get("NextToken")
            if not token:
                return rows

    # ---- 쓰기 ----
    def write(self, table, rows):
        if not rows:
            return
        spec = TABLE_SPECS.get(table)
        if spec is None:
            raise ValueError(f"쓸 수 없는 표입니다: {table!r} (허용: {sorted(TABLE_SPECS)})")
        for r in rows:
            extra = set(r) - set(spec["columns"])
            if extra:
                raise ValueError(f"{table} 표에 없는 컬럼입니다: {sorted(extra)}")
        cols = list(spec["columns"]) + list(spec["partitions"])
        head = f"INSERT INTO {spec['database']}.{table} ({', '.join(_q(c) for c in cols)}) VALUES "
        batch, size = [], len(head)
        for r in rows:
            values = _row_sql(r, spec)
            if batch and size + len(values) + 2 > MAX_QUERY_BYTES:
                self._run(head + ", ".join(batch))
                batch, size = [], len(head)
            batch.append(values)
            size += len(values) + 2
        if batch:
            self._run(head + ", ".join(batch))


def _q(name):
    return f'"{name}"'


def _lit(value, type_name):
    if value is None:
        return "NULL"
    if type_name == "timestamp":
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("T", " "))
        return f"TIMESTAMP '{dt.strftime('%Y-%m-%d %H:%M:%S')}'"
    if type_name in ("bigint", "double"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"숫자 컬럼에 숫자가 아닌 값이 들어왔습니다: {type(value).__name__}")
        return repr(int(value)) if type_name == "bigint" else repr(float(value))
    return "'" + str(value).replace("'", "''") + "'"


def _row_sql(row, spec):
    parts = [_lit(row.get(c), t) for c, t in spec["columns"].items()]
    if spec["partitions"]:
        pt = row.get(spec["partition_by"])
        if pt is None:
            raise ValueError(f"파티션 기준 컬럼 {spec['partition_by']}가 비어 있습니다")
        dt = pt if isinstance(pt, datetime) else datetime.fromisoformat(str(pt).replace("T", " "))
        values = {"dt": f"'{dt:%Y-%m-%d}'", "hour": f"'{dt:%H}'"}
        parts += [values[name] for name in spec["partitions"]]
    return "(" + ", ".join(parts) + ")"
