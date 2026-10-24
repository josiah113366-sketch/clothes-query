"""Bounded EKS check using the image's actual Gold B ingestion functions.

This changes only the stream lifetime. It does not produce Kafka messages,
change offsets, clear checkpoints, or replace application processing logic.
"""
import json
import os
import sys
import time
import boto3

from pipelines.gold_b.format_check import FormatChecker
from pipelines.gold_b.jobs.streaming_ingest import (
    Settings, build_query, load_config, spark_session,
)
from pipelines.gold_b.ledger import open_store


def main():
    batches = int(os.environ.get("GOLD_B_VALIDATION_BATCHES", "2"))
    seconds = int(os.environ.get("GOLD_B_VALIDATION_SECONDS", "240"))
    if not 1 <= batches <= 3 or not 60 <= seconds <= 600:
        raise ValueError("Validation must have a small bounded duration")
    settings = Settings.from_env(os.environ)
    identity = boto3.client("sts", region_name="ap-northeast-1").get_caller_identity()
    expected_role = "clothes-query-dev-data-gold-b-ingest-driver"
    if identity["Account"] != "827913617635" or (":" + "assumed-role/" + expected_role + "/") not in identity["Arn"]:
        raise RuntimeError("Unexpected AWS execution identity")
    spark = spark_session()
    query = None
    progress = {}
    try:
        query = build_query(spark, settings=settings, config=load_config(),
                            checker=FormatChecker(rules_path=os.environ.get("GOLD_B_RULES_PATH") or None),
                            store=open_store(settings.ledger_root))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if query.exception() is not None:
                raise RuntimeError("Gold B stream failed; inspect private Spark logs")
            for item in query.recentProgress:
                progress[item["batchId"]] = item
            if len(progress) >= batches:
                break
            if not query.isActive:
                raise RuntimeError("Gold B stream stopped before validation completed")
            time.sleep(2)
        if len(progress) < batches:
            raise TimeoutError("No sufficient completed microbatches within validation window")
        query.stop()
        report = {
            "code_ref": os.environ.get("GOLD_B_CODE_REF"),
            "spark_version": spark.version,
            "python_version": sys.version.split()[0],
            "pod_identity_role": expected_role,
            "completed_batches": [
                {"batch_id": p["batchId"], "input_rows": p["numInputRows"],
                 "timestamp": p["timestamp"], "duration_ms": p["durationMs"],
                 "sources": [{key: source.get(key) for key in ("startOffset", "endOffset")}
                             for source in p["sources"]]}
                for _, p in sorted(progress.items())
            ],
        }
        print("GOLD_B_VALIDATION_RESULT=" + json.dumps(report), flush=True)
    finally:
        if query is not None and query.isActive:
            query.stop()
        spark.stop()


if __name__ == "__main__":
    main()
