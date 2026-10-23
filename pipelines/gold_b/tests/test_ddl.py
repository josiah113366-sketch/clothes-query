"""Gold B 테이블 정의(DDL)와 샘플 메시지가 설계 문서와 맞는지 확인한다.

Athena에 붙지 않고 로컬에서만 확인한다:
- DDL 컬럼·타입·시간 폴더·파티션 프로젝션이 설계 표와 같은가
- 샘플 메시지의 모양과 기대 결과가 설계 규칙에 맞는가
- 샘플로 만든 원장 줄을 DDL 타입의 Parquet으로 시간 폴더에 쓰고 다시 읽을 수 있는가
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re

import pytest

from pipelines.timestamps import parse_iso_datetime

HERE = Path(__file__).resolve().parent
DDL_DIR = HERE.parent / "ddl"
SAMPLES = HERE / "samples"
BUCKET_PREFIX = "s3://clothes-query-datalake/gold_b/"

# docs/design/gold-b/README.md 「저장」의 표를 그대로 옮긴 것
EXPECTED = {
    "payment_events": [
        ("payment_id", "STRING"), ("order_id", "STRING"), ("attempt_no", "INT"),
        ("pg", "STRING"), ("status", "STRING"), ("failure_code", "STRING"),
        ("completed_at", "TIMESTAMP"), ("payment_content_hash", "STRING"),
        ("fingerprint_version", "STRING"), ("kafka_partition", "INT"), ("kafka_offset", "BIGINT"),
        ("loaded_at", "TIMESTAMP"), ("cdc_op", "STRING"), ("source_ts_ms", "BIGINT"), ("rule_version", "STRING"),
    ],
    "topic_messages": [
        ("topic", "STRING"), ("kafka_partition", "INT"), ("kafka_offset", "BIGINT"),
        ("kafka_timestamp", "TIMESTAMP"), ("loaded_at", "TIMESTAMP"),
    ],
    "bronze_lag_snapshots": [
        ("collected_at", "TIMESTAMP"), ("topic", "STRING"), ("kafka_partition", "INT"),
        ("end_offset", "BIGINT"), ("committed_offset", "BIGINT"), ("lag_msgs", "BIGINT"),
        ("lag_sec", "DOUBLE"), ("connector_state", "STRING"),
    ],
    "malformed_events": [
        ("topic", "STRING"), ("kafka_partition", "INT"), ("kafka_offset", "BIGINT"),
        ("kafka_timestamp", "TIMESTAMP"), ("field", "STRING"), ("reason", "STRING"),
        ("raw_sample", "STRING"), ("rule_version", "STRING"), ("loaded_at", "TIMESTAMP"),
        ("record_key", "STRING"), ("source_ts_ms", "BIGINT"),
    ],
    "reprocess_events": [
        ("request_id", "STRING"), ("step", "STRING"), ("at", "TIMESTAMP"), ("actor", "STRING"),
        ("reason", "STRING"), ("window_start", "TIMESTAMP"), ("window_end", "TIMESTAMP"),
        ("rule_version", "STRING"), ("source", "STRING"), ("attempt", "INT"),
        ("parent_request_id", "STRING"), ("detail", "STRING"),
    ],
}
LEDGERS = ("payment_events", "topic_messages", "bronze_lag_snapshots", "malformed_events")
TOPICS = {"payments", "orders", "order-items", "members-events", "clickstream", "reviews.raw"}
UNCHECKED_TOPICS = {"reviews.raw"}   # Gold B가 형식 검사하지 않는 토픽 (2026-10-23 결정). topic_messages에만 남는다
REASONS = {"PARSE_ERROR", "MISSING_FIELD", "TYPE_MISMATCH", "INVALID_VALUE"}
# 결제 내용 지문에 들어가는 업무 필드 9개. amount·method·requested_at은 지문에만 들어간다
FINGERPRINT_FIELDS = ("order_id", "attempt_no", "method", "pg", "amount", "status",
                      "failure_code", "requested_at", "completed_at")


# ---------- DDL 읽기 ----------

def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] if not line.lstrip().startswith("--") else ""
                     for line in sql.splitlines())


def parse_ddl(table: str) -> dict:
    sql = _strip_comments((DDL_DIR / f"{table}.sql").read_text(encoding="utf-8"))
    head = re.search(rf"CREATE EXTERNAL TABLE IF NOT EXISTS gold_b\.{table} \((.*?)\n\)", sql, re.S)
    assert head, f"{table}: CREATE EXTERNAL TABLE gold_b.{table} 문을 찾지 못함"
    columns = re.findall(r"^\s*(\w+)\s+(STRING|INT|BIGINT|DOUBLE|TIMESTAMP)\b", head.group(1), re.M)
    partitions = re.search(r"PARTITIONED BY \(([^)]*)\)", sql)
    location = re.search(r"LOCATION '([^']+)'", sql)
    props = dict(re.findall(r"'([\w.]+)'\s*=\s*'([^']*)'", sql))
    return {
        "columns": columns,
        "partitions": re.findall(r"(\w+) (\w+)", partitions.group(1)) if partitions else [],
        "location": location.group(1) if location else None,
        "props": props,
        "stored_as_parquet": "STORED AS PARQUET" in sql,
    }


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_columns_match_design(table):
    assert parse_ddl(table)["columns"] == EXPECTED[table]


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_location_and_format(table):
    ddl = parse_ddl(table)
    assert ddl["stored_as_parquet"]
    assert ddl["location"] == f"{BUCKET_PREFIX}{table}/"
    assert ddl["props"].get("parquet.compression") == "SNAPPY"


@pytest.mark.parametrize("table", LEDGERS)
def test_ledger_hour_folders_and_projection(table):
    ddl = parse_ddl(table)
    assert ddl["partitions"] == [("dt", "STRING"), ("hour", "STRING")]
    props = ddl["props"]
    assert props["projection.enabled"] == "true"
    assert props["projection.dt.type"] == "date"
    assert props["projection.dt.format"] == "yyyy-MM-dd"
    assert props["projection.dt.range"].endswith(",NOW")
    assert (props["projection.hour.type"], props["projection.hour.range"],
            props["projection.hour.digits"]) == ("integer", "0,23", "2")
    assert props["storage.location.template"] == ddl["location"] + "dt=${dt}/hour=${hour}/"


def test_reprocess_events_has_no_hour_folders():
    ddl = parse_ddl("reprocess_events")
    assert ddl["partitions"] == []
    assert "projection.enabled" not in ddl["props"]


def test_partition_column_name_is_kafka_partition_everywhere():
    for table in EXPECTED:
        names = [name for name, _ in parse_ddl(table)["columns"]]
        assert "partition" not in names, f"{table}: 예약어 partition 대신 kafka_partition"


def test_database_ddl():
    sql = (DDL_DIR / "database.sql").read_text(encoding="utf-8")
    assert "CREATE DATABASE IF NOT EXISTS gold_b" in sql
    assert f"LOCATION '{BUCKET_PREFIX}'" in sql


# ---------- 샘플 ----------

def load_samples() -> list[dict]:
    return [item for name in ("payments.json", "other_topics.json")
            for item in json.loads((SAMPLES / name).read_text(encoding="utf-8"))]


def load_payment_updates() -> list[dict]:
    """결제 수정 시나리오 (payment_updates.json). 형식 검사·정리 뷰 시험이 쓰고, 적재·재처리 시험의 건수에는 넣지 않는다."""
    return json.loads((SAMPLES / "payment_updates.json").read_text(encoding="utf-8"))


def _utc(text: str) -> datetime:
    parsed = parse_iso_datetime(text)   # 공통 시각 파서 (Python 3.10에서도 Z·소수초를 읽음)
    assert parsed.utcoffset() is not None
    return parsed


def stand_in_fingerprint(value: dict) -> str:
    """시험용 대체 지문. 실제 규칙은 pipelines/payment_fingerprint.py(2단계, Silver와 같은 함수)에서 정한다.

    여기서는 '업무 필드 9개가 같으면 같은 값, 다르면 다른 값'만 맞으면 된다 (Kafka 위치·__op는 넣지 않음).
    """
    return json.dumps([value.get(f) for f in FINGERPRINT_FIELDS], ensure_ascii=False)


def test_samples_shape():
    samples = load_samples() + load_payment_updates()
    names = [s["name"] for s in samples]
    assert len(names) == len(set(names))
    locations = [(s["kafka"]["topic"], s["kafka"]["partition"], s["kafka"]["offset"]) for s in samples]
    assert len(locations) == len(set(locations)), "같은 Kafka 위치가 두 번 나옴"
    for s in samples:
        assert s["kafka"]["topic"] in TOPICS
        _utc(s["kafka"]["timestamp"])
        assert ("value" in s) != ("value_raw" in s), f"{s['name']}: value와 value_raw 중 하나만"
        expected = s["expected"]
        for error in expected["malformed"]:
            assert error["field"]
            if error["reason"] is None:
                assert expected.get("note"), f"{s['name']}: 사유 미정이면 note 필요"
            else:
                assert error["reason"] in REASONS
        if expected["malformed"]:
            assert not expected["payment_events"], f"{s['name']}: 깨진 메시지는 payment_events에 안 쌓임"


def test_every_topic_has_a_normal_and_a_broken_sample():
    samples = load_samples()
    normal = {s["kafka"]["topic"] for s in samples if not s["expected"]["malformed"]}
    broken = {s["kafka"]["topic"] for s in samples if s["expected"]["malformed"]}
    assert normal == TOPICS
    assert broken == TOPICS - UNCHECKED_TOPICS


def test_payment_samples_expect_only_ledgers():
    """결제 샘플의 expected는 원장(①·④) 결과만 적는다. 결제마다의 뷰 결과는 payment_states.json에 있다 (2026-10-23)."""
    payments = [s for s in load_samples() + load_payment_updates() if s["kafka"]["topic"] == "payments"]
    for s in payments:
        assert set(s["expected"]) <= {"payment_events", "malformed", "note"}, s["name"]
        if s["expected"]["payment_events"]:
            assert s["value"]["__op"] in {"c", "r", "u"}

    # 중복: 지문이 같고 위치만 다름
    by_name = {s["name"]: s for s in payments}
    original, duplicate = by_name["success_pg_a"], by_name["duplicate_of_success_pg_a"]
    assert stand_in_fingerprint(original["value"]) == stand_in_fingerprint(duplicate["value"])
    assert original["kafka"]["offset"] != duplicate["kafka"]["offset"]
    # 내용이 바뀐 두 쌍: 같은 결제, 같은 파티션에서 지문이 다름 (뷰는 offset이 뒤인 것을 보여준다)
    for first, second in (("conflict_first", "conflict_second"), ("conflict_amount_first", "conflict_amount_second")):
        a, b = by_name[first], by_name[second]
        assert a["value"]["payment_id"] == b["value"]["payment_id"]
        assert a["kafka"]["partition"] == b["kafka"]["partition"] and a["kafka"]["offset"] < b["kafka"]["offset"]
        assert stand_in_fingerprint(a["value"]) != stand_in_fingerprint(b["value"])


def test_samples_have_no_personal_values():
    files = sorted(SAMPLES.glob("*.json"))
    assert {f.name for f in files} >= {"payments.json", "other_topics.json", "payment_updates.json", "payment_states.json"}
    text = "".join(f.read_text(encoding="utf-8") for f in files)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "이메일 모양 값"
    # 하이픈 없는 10자리는 H&M article_id(예: 0108775015)와 겹쳐서 하이픈 있는 꼴만 본다
    assert not re.search(r"01[016789]-\d{3,4}-\d{4}", text), "전화번호 모양 값"


# ---------- 샘플 → 원장 Parquet → 다시 읽기 ----------

def _arrow_schema(table: str):
    pa = pytest.importorskip("pyarrow")
    types = {"STRING": pa.string(), "INT": pa.int32(), "BIGINT": pa.int64(),
             "DOUBLE": pa.float64(), "TIMESTAMP": pa.timestamp("us")}
    return pa.schema([(name, types[kind]) for name, kind in parse_ddl(table)["columns"]])


def ledger_rows(samples: list[dict], loaded_at: datetime) -> dict[str, list[dict]]:
    """샘플의 기대 결과대로 원장 줄을 만든다 (형식 검사 코드가 생기기 전의 기대값)."""
    rows = {"payment_events": [], "topic_messages": [], "malformed_events": []}
    for s in samples:
        k = s["kafka"]
        at = _utc(k["timestamp"]).replace(tzinfo=None)
        rows["topic_messages"].append({"topic": k["topic"], "kafka_partition": k["partition"],
                                       "kafka_offset": k["offset"], "kafka_timestamp": at,
                                       "loaded_at": loaded_at})
        if s["expected"]["payment_events"]:
            v = s["value"]
            rows["payment_events"].append({
                "payment_id": v["payment_id"], "order_id": v["order_id"], "attempt_no": v["attempt_no"],
                "pg": v["pg"], "status": v["status"], "failure_code": v["failure_code"],
                "completed_at": _utc(v["completed_at"]).replace(tzinfo=None),
                "payment_content_hash": stand_in_fingerprint(v), "fingerprint_version": "test",
                "kafka_partition": k["partition"], "kafka_offset": k["offset"], "loaded_at": loaded_at})
        for i, error in enumerate(s["expected"]["malformed"]):
            rows["malformed_events"].append({
                "topic": k["topic"], "kafka_partition": k["partition"], "kafka_offset": k["offset"],
                "kafka_timestamp": at, "field": error["field"], "reason": error["reason"],
                "raw_sample": "<masked>" if i == 0 else None, "rule_version": "test",
                "loaded_at": loaded_at})
    return rows


EVENT_TIME = {"payment_events": "completed_at", "topic_messages": "kafka_timestamp",
              "malformed_events": "kafka_timestamp"}


def test_sample_ledgers_round_trip_through_hour_folders(tmp_path):
    pa = pytest.importorskip("pyarrow")
    ds = pytest.importorskip("pyarrow.dataset")
    pq = pytest.importorskip("pyarrow.parquet")
    samples = load_samples()
    rows = ledger_rows(samples, loaded_at=datetime(2026, 10, 21, 6, 30))

    for table, items in rows.items():
        schema = _arrow_schema(table)
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in items:
            t = row[EVENT_TIME[table]]
            groups.setdefault((t.strftime("%Y-%m-%d"), t.strftime("%H")), []).append(row)
        for (dt, hour), part in groups.items():
            folder = tmp_path / table / f"dt={dt}" / f"hour={hour}"
            folder.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(part, schema=schema), folder / "part-0.parquet",
                           compression="snappy")

        read = ds.dataset(tmp_path / table, format="parquet", partitioning="hive").to_table()
        assert read.num_rows == len(items)
        for name, _ in parse_ddl(table)["columns"]:
            assert read.schema.field(name).type == schema.field(name).type

    # 기대 건수: 결제 10줄(중복, 내용이 바뀐 두 쌍, 수정 u 포함. 모르는 실패 코드는 형식 오류), 메시지 31줄, 오류 = 샘플 기대 오류 합
    assert len(rows["payment_events"]) == 10
    assert len(rows["topic_messages"]) == len(samples) == 31
    assert len(rows["malformed_events"]) == sum(len(s["expected"]["malformed"]) for s in samples)
    per_message = Counter((r["topic"], r["kafka_partition"], r["kafka_offset"]) for r in rows["malformed_events"])
    assert max(per_message.values()) == 3, "오류 여러 개 샘플은 3줄"
