"""Run inside a temporary workload Pod; use only synthetic probe objects."""

import json
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def main():
    role = os.environ["PROBE_ROLE"]
    bucket = os.environ["PROBE_BUCKET"]
    run_id = os.environ["PROBE_RUN_ID"]
    other = "detection" if role == "investigation" else "investigation"
    service_account = "detection-job" if role == "detection" else "investigation-agent"
    config = Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2})
    session = boto3.Session(region_name="ap-northeast-1")
    s3 = session.client("s3", config=config)
    athena = session.client("athena", config=config)
    checks = []

    def denied(label, fn):
        try:
            fn()
        except ClientError as error:
            assert error.response["Error"]["Code"] in {
                "AccessDenied",
                "AccessDeniedException",
                "403",
            }, label
            checks.append(label)
        else:
            raise AssertionError(label + " unexpectedly allowed")

    identity = session.client("sts", config=config).get_caller_identity()
    assert "/clothes-query-dev-" + service_account + "/" in identity["Arn"]
    checks.append("correct_pod_identity")
    body = b'{"infra_probe":true}'
    source = "gold_b/_infra-checks/" + run_id + ".json"
    truth = "ground_truth/_infra-checks/" + run_id + ".json"
    own = "athena-results/" + role + "/_infra-checks/" + run_id + ".json"
    foreign = "athena-results/" + other + "/_infra-checks/" + run_id + ".json"
    assert s3.get_object(Bucket=bucket, Key=source)["Body"].read() == body
    checks.append("gold_b_read")
    s3.list_objects_v2(Bucket=bucket, Prefix="gold_b/", MaxKeys=1)
    checks.append("gold_b_list")
    s3.put_object(Bucket=bucket, Key=own, Body=body)
    assert s3.get_object(Bucket=bucket, Key=own)["Body"].read() == body
    checks.append("own_results_write_read")
    denied("ground_truth_read_denied", lambda: s3.get_object(Bucket=bucket, Key=truth))
    denied(
        "ground_truth_version_read_denied",
        lambda: s3.get_object(
            Bucket=bucket, Key=truth, VersionId=os.environ["PROBE_TRUTH_VERSION"]
        ),
    )
    denied(
        "ground_truth_list_denied",
        lambda: s3.list_objects_v2(Bucket=bucket, Prefix="ground_truth/", MaxKeys=1),
    )
    denied(
        "foreign_results_read_denied", lambda: s3.get_object(Bucket=bucket, Key=foreign)
    )
    denied("root_listing_denied", lambda: s3.list_objects_v2(Bucket=bucket, MaxKeys=1))
    denied(
        "business_data_write_denied",
        lambda: s3.put_object(Bucket=bucket, Key=source, Body=body),
    )
    denied(
        "foreign_workgroup_denied",
        lambda: athena.start_query_execution(
            QueryString="SELECT 1 AS infra_probe",
            WorkGroup="clothes-query-dev-" + other,
        ),
    )
    query_id = athena.start_query_execution(
        QueryString="SELECT 1 AS infra_probe",
        WorkGroup="clothes-query-dev-" + role,
    )["QueryExecutionId"]
    print(
        json.dumps({"event": "query_started", "role": role, "query_id": query_id}),
        flush=True,
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        query = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = query["Status"]["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        time.sleep(2)
    assert state == "SUCCEEDED", "synthetic_query_did_not_succeed"
    assert query["ResultConfiguration"]["OutputLocation"].startswith(
        "s3://" + bucket + "/athena-results/" + role + "/"
    )
    rows = athena.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]
    assert rows[-1]["Data"][0]["VarCharValue"] == "1"
    checks.append("own_athena_query_and_results")
    print(
        json.dumps(
            {"role": role, "passed": True, "checks": checks, "query_id": query_id}
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, BotoCoreError, ClientError, KeyError, ValueError) as error:
        code = (
            error.response["Error"]["Code"]
            if isinstance(error, ClientError)
            else type(error).__name__
        )
        print(json.dumps({"passed": False, "error_code": code}), flush=True)
        raise SystemExit(1)
