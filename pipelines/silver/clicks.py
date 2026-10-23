"""문서의 클릭 이벤트를 방문·상품 연결용 Silver로 정리한다."""
from __future__ import annotations

import argparse
from itertools import islice
from pathlib import Path
from zoneinfo import ZoneInfo

from pipelines.format_rules import (
    DEFAULT_RULES,
    FormatError,
    FormatRules,
    RuleConfigError,
)

from .common import RowError, collect_unique, decode_record, run_local, timestamp

CHECK_VERSION = "clicks.v2"
KST = ZoneInfo("Asia/Seoul")


def _normalize(raw: dict, rules: FormatRules) -> dict:
    rules.validate("clickstream", raw)
    row = {field: raw[field] for field in (
        "event_id", "event_type", "member_id", "article_id", "session_id",
    )}
    utc = timestamp(raw, "event_time")
    kst = utc.astimezone(KST)
    return {**row, "event_time_utc": utc.isoformat(), "event_time_kst": kst.isoformat(),
            "event_date_kst": kst.date().isoformat()}


def build_clicks(events: list[dict], rules: FormatRules | None = None) -> dict[str, list[dict]]:
    rules = rules if rules is not None else FormatRules()
    if "clickstream" not in rules.datasets:
        raise RuleConfigError("클릭 데이터셋의 공통 규칙이 없습니다")
    clean, issues, summary = collect_unique(
        events, "clickstream", "event_id", lambda raw: _normalize(raw, rules), CHECK_VERSION)
    summary["output_counts"] = {"click_events": len(clean)}
    summary["format_rules"] = rules.reference()
    return {"click_events": clean, "quarantined_records": issues, "dq_results": [summary]}


def run(input_root: str, output_root: str, input_complete: bool = False,
        rules_path: str | Path | None = None) -> dict:
    rules = FormatRules(DEFAULT_RULES if rules_path is None else rules_path)
    return run_local({"clickstream": input_root}, output_root, "clicks", CHECK_VERSION,
                     lambda rows: build_clicks(rows["clickstream"], rules), input_complete=input_complete,
                     rule_metadata=rules.reference())


def build_clicks_spark(spark, paths, rules_path=DEFAULT_RULES, max_key_rows=10000):
    """원문은 Executor에서 읽고 event_id별 기존 검사·중복/충돌 규칙을 공유한다."""
    from pyspark.sql import functions as F

    from pipelines.spark_batch import SCHEMAS, _spark_uri, dumps

    if "clickstream" not in FormatRules(rules_path).datasets:
        raise RuleConfigError("클릭 데이터셋의 공통 규칙이 없습니다")

    def parse(files):
        for uri, text in files:
            uri = "s3://" + uri[6:] if uri.startswith("s3a://") else uri
            for number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
                if line.strip():
                    raw = decode_record(line, uri, number)
                    key = raw.get("event_id")
                    known = not isinstance(key, bool) and isinstance(key, (str, int))
                    yield ("key:" + type(key).__name__ + ":" + str(key) if known else
                           "row:" + uri + ":" + str(number)), raw

    def process(groups):
        rules = FormatRules(rules_path)
        for _, values in groups:
            group = list(islice(values, max_key_rows + 1))
            if len(group) > max_key_rows:
                raise ValueError("동일 클릭 ID 입력이 행 한도를 넘습니다")
            result = build_clicks(group, rules)
            for name, rows in result.items():
                for row in rows:
                    if name == "quarantined_records":
                        row["source_record_id"] = f"clickstream:{row['source_file']}:{row['source_line']}"
                    yield name, dumps(row)
            for raw in group:
                candidate = {k: raw.get(k) if isinstance(raw.get(k), str) else None
                             for k in ("event_id", "session_id", "article_id", "event_type")}
                try:
                    normalized = _normalize(raw, rules)
                    candidate.update(valid=True, event_time_kst=normalized["event_time_kst"])
                except (RowError, FormatError):
                    candidate.update(valid=False, event_time_kst=None)
                candidate.update(source_file=raw["_input_source"]["file"], source_line=raw["_input_source"]["line"])
                yield "click_impact_candidates", dumps(candidate)

    files = spark.sparkContext.wholeTextFiles(",".join(_spark_uri(p) for p in paths), minPartitions=2)
    tall = spark.createDataFrame(files.mapPartitions(parse).groupByKey().mapPartitions(process),
                                "table_name string, payload string").persist()
    schema = ", ".join(f"{k} string" for k in ("event_id", "event_type", "member_id", "article_id", "session_id",
                                              "event_time_utc", "event_time_kst", "event_date_kst"))
    clean = tall.filter("table_name = 'click_events'").select(
        F.from_json("payload", schema, {"mode": "FAILFAST"}).alias("r")).select("r.*")
    issues = tall.filter("table_name = 'quarantined_records'").select(
        F.from_json("payload", SCHEMAS["quarantined_records"], {"mode": "FAILFAST"}).alias("r")).select("r.*")
    metrics = ("input_count", "accepted_count", "quarantined_count", "duplicate_count", "conflict_count", "pending_count")
    dq = tall.filter("table_name = 'dq_results'").select(
        F.from_json("payload", ", ".join(f"{k} long" for k in metrics)).alias("r")).select("r.*")
    summary = dq.agg(*[F.coalesce(F.sum(k), F.lit(0)).alias(k) for k in metrics]).withColumn(
        "source_dataset", F.lit("clickstream")).withColumn("check_version", F.lit(CHECK_VERSION)).withColumn(
        "format_rules", F.lit(dumps(FormatRules(rules_path).reference()))).withColumn(
        "status", F.when(F.col("quarantined_count") > 0, "INCOMPLETE").otherwise("PASS"))
    candidates = tall.filter("table_name = 'click_impact_candidates'").select(F.from_json("payload",
        "event_id string, session_id string, article_id string, event_type string, event_time_kst string, valid boolean, source_file string, source_line long",
        {"mode": "FAILFAST"}).alias("r")).select("r.*")
    return {"click_impact_candidates": candidates, "click_events": clean.withColumn("event_date_kst", F.to_date("event_date_kst")),
            "quarantined_records": issues, "dq_results": summary, "_cache": (tall,)}


def main() -> None:
    parser = argparse.ArgumentParser(description="문서 기준 클릭 JSONL → 로컬 Silver")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--input-complete", action="store_true", help="필요한 전체 클릭 이력을 준비했음을 실행자가 확인")
    parser.add_argument("--rules-path", help="공통 입력 규칙 YAML. 생략하면 저장소 기본 규칙")
    args = parser.parse_args()
    manifest = run(args.input_root, args.output_root, args.input_complete, args.rules_path)
    print(f"클릭 Silver {manifest['status']}: {manifest['output_counts']}")
    print(f"대표 결과: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
