"""Runs only inside the isolated Moto fixture; prints counts, never record bodies."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import ClientError

BUCKET = "cq-pipeline-smoke"
PREFIX = "infra-smoke/smoke.public.cdc_probe/"


def main():
    mode = sys.argv[1]
    assert mode in {"init", "initial", "resumed"}
    client = boto3.client("s3", endpoint_url="http://localhost:5000", region_name="us-east-1")
    if mode == "init":
        try:
            client.head_bucket(Bucket=BUCKET)
        except ClientError as error:
            if error.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
                raise
            client.create_bucket(Bucket=BUCKET)
        print(json.dumps({"local_bucket_ready": True}))
        return
    objects = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        objects.extend(page.get("Contents", []))
    assert objects, "No local Sink objects yet"
    assert all(obj["Key"].startswith(PREFIX) for obj in objects), "Unexpected output prefix"
    def read_records(obj):
        body = client.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read().decode("utf-8")
        return [json.loads(line) for line in body.splitlines() if line.strip()]
    # The compact CDC burst creates 1000 small objects. Read all of them, bounded
    # in parallel, so probe latency does not mask successful delivery.
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = [record for batch in pool.map(read_records, objects) for record in batch]
    expected = [("r", 1, 10), ("c", 2, 20), ("u", 1, 11), ("d", 2, 20), ("c", 3, 30), ("c", 4, 40)]
    if mode == "resumed":
        expected.append(("c", 5, 50))
    for op, row_id, value in expected:
        field = "before" if op == "d" else "after"
        assert any(row.get("op") == op and row.get(field) == {"id": row_id, "value": value}
                   for row in records), "Expected CDC event not stored yet"
    print(json.dumps({"objects": len(objects), "records": len(records), "required_events": len(expected)}))


if __name__ == "__main__":
    main()
