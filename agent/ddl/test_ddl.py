"""DDL 파일이 코드(agent/detect/athena_io.py의 TABLE_SPECS)와 같은지 확인한다. Athena는 부르지 않는다.

실행: python3 test_ddl.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "detect"))
from athena_io import TABLE_SPECS, AthenaIO      # noqa: E402

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


TYPES = {"STRING": "string", "TIMESTAMP": "timestamp", "BIGINT": "bigint", "DOUBLE": "double"}
FILES = {"anomaly": "anomaly.sql", "detection_runs": "detection_runs.sql",
         "investigation_reports": "investigation_reports.sql", "investigation_runs": "investigation_runs.sql"}


def parse(path):
    text = open(os.path.join(HERE, path), encoding="utf-8").read()
    head = re.search(r"CREATE EXTERNAL TABLE IF NOT EXISTS (\w+)\.(\w+) \((.*?)\n\)\n", text, re.S)
    cols, comments = [], []
    for line in head.group(3).split("\n"):
        m = re.match(r"\s*(\w+)\s+(STRING|TIMESTAMP|BIGINT|DOUBLE)\b(.*)", line)
        if m:
            cols.append((m.group(1), TYPES[m.group(2)]))
            comments.append("COMMENT '" in m.group(3))
    parts = re.search(r"PARTITIONED BY \((.*?)\)", text)
    parts = [p.strip().split()[0] for p in parts.group(1).split(",")] if parts else []
    loc = re.search(r"LOCATION '([^']+)'", text).group(1)
    tmpl = re.search(r"'storage.location.template'\s*=\s*'([^']+)'", text).group(1)
    return {"db": head.group(1), "table": head.group(2), "columns": cols, "comments": comments, "partitions": parts, "location": loc, "template": tmpl}


for table, path in FILES.items():
    d, spec = parse(path), TABLE_SPECS[table]
    check(f"{table}: DDL의 데이터베이스와 표 이름이 코드와 같음", (d["db"], d["table"]), (spec["database"], table))
    check(f"{table}: DDL 컬럼 이름·타입·순서가 코드(TABLE_SPECS)와 같음", d["columns"], list(spec["columns"].items()))
    check(f"{table}: 모든 컬럼에 설명(COMMENT)이 있음", all(d["comments"]), True)
    check(f"{table}: 파티션 컬럼이 코드와 같음", d["partitions"], list(spec["partitions"]))
    folder = "/".join(d["location"].rstrip("/").split("/")[-2:])
    check(f"{table}: 저장 위치가 <데이터베이스 폴더>/<표 이름>/", folder, f"{'agent' if d['db'] == 'agent' else 'gold_b'}/{table}")
    check(f"{table}: 저장 위치 템플릿이 파티션과 같은 모양", d["template"], d["location"] + "dt=${dt}/")


class Fake:
    def __init__(self):
        self.sql = None

    def start_query_execution(self, QueryString, WorkGroup, QueryExecutionContext):
        self.sql = QueryString
        return {"QueryExecutionId": "q"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}


for table, spec in TABLE_SPECS.items():
    if table == "reprocess_events":
        continue
    fake = Fake()
    row = {spec["partition_by"]: "2026-10-21 09:00:00"}
    AthenaIO("w", client=fake, sleep=lambda s: None).write(table, [row])
    inserted = re.search(r"INSERT INTO (\w+)\.(\w+) \((.*?)\) VALUES", fake.sql)
    names = [n.strip('"') for n in inserted.group(3).split(", ")]
    d = parse(FILES[table])
    check(f"{table}: INSERT 문의 컬럼 순서가 DDL의 컬럼 + 파티션과 같음", names, [c for c, _ in d["columns"]] + d["partitions"])
    check(f"{table}: INSERT 문의 표가 DDL의 표와 같음", (inserted.group(1), inserted.group(2)), (d["db"], d["table"]))

view = open(os.path.join(HERE, "views", "anomaly_current.sql"), encoding="utf-8").read()
cols = list(TABLE_SPECS["anomaly"]["columns"])
check("anomaly_current 뷰가 이상 표의 모든 컬럼을 고르고 파티션 컬럼(dt)과 순번(rn)은 내보내지 않음", all(re.search(rf"\b{c}\b", view.split("FROM (")[0]) for c in cols) and "dt" not in view.split("FROM (")[0].split(), True)
check("anomaly_current 뷰가 이상별(anomaly_id) 가장 최근 줄 하나만 고름", ("PARTITION BY anomaly_id" in view, "ORDER BY detected_at DESC, run_id DESC" in view, "WHERE rn = 1" in view), (True, True, True))
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
