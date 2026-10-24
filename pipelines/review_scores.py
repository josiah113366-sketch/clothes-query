"""Iceberg 최신 점수 뷰를 조회하고 실행별 불변 Parquet 입력으로 고정한다."""
import hashlib
import json
import re
import time
from datetime import date

from pipelines.r6_publication import S3Store, encode

VIEW = "clothes_query_dev_review_score.review_aspect_scores_latest"


def snapshot_scores(root, run_id, start, end, options, athena, s3, wait=time.sleep):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id) or "'" in root:
        raise ValueError("점수 고정 경로 형식 오류")
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if end < start or not options.get("workgroup") or set(options) - {"workgroup", "timeout_seconds"}:
        raise ValueError("최신 점수 조회의 날짜·workgroup 설정 오류")
    timeout = options.get("timeout_seconds", 600)
    if type(timeout) is not int or not 1 <= timeout <= 1800:
        raise ValueError("Athena 대기 한도는 1~1800초입니다")
    store = S3Store(root, s3)
    base = f"pipelines/input-manifests/review-scores/{run_id}"
    prefix = store.uri(base + "/data/")
    sql = ("UNLOAD (SELECT review_id, aspect, CAST(score AS BIGINT) AS score, model_version, "
           "CAST(model_version_no AS VARCHAR) AS model_version_no, review_date FROM " + VIEW +
           f" WHERE review_date BETWEEN DATE '{start}' AND DATE '{end}') TO '{prefix}' "
           "WITH (format = 'PARQUET', compression = 'SNAPPY')")
    # 같은 run/SQL을 재시도해도 다른 시점의 최신 모델을 다시 조회하지 않는다.
    token = hashlib.sha256((sql + options["workgroup"]).encode()).hexdigest()
    old, _ = store.get(base + "/manifest.json")
    if old:
        manifest = json.loads(old)
        if manifest.get("query_token") != token:
            raise ValueError("같은 리뷰 실행 ID의 점수 조회 조건이 다릅니다")
        return manifest
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=options["workgroup"],
                                       ClientRequestToken=token)["QueryExecutionId"]
    deadline = time.monotonic() + timeout
    while True:
        query = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = query["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            raise RuntimeError("최신 점수 조회 실패: " + qid + " (부분 파일은 재사용하지 않습니다)")
        if time.monotonic() >= deadline:
            athena.stop_query_execution(QueryExecutionId=qid)
            raise TimeoutError("최신 점수 조회 시간 초과: " + qid)
        wait(2)
    objects = []
    for page in athena.get_paginator("get_query_results").paginate(
            QueryExecutionId=qid, QueryResultType="DATA_MANIFEST"):
        for row in page["ResultSet"]["Rows"]:
            uri = row.get("Data", [{}])[0].get("VarCharValue", "")
            if not uri.startswith("s3://"):
                continue  # manifest 열 머리글
            if not uri.startswith(prefix):
                raise ValueError("Athena 결과 manifest의 파일이 실행 고정 경로 밖에 있습니다")
            key = uri[len(store.root) + 1:]
            head = s3.head_object(Bucket=store.bucket, Key=store.key(key))
            objects.append({"dataset": "analysis", "uri": uri, "etag": head["ETag"],
                            "size": head["ContentLength"]})
    manifest = {"query_execution_id": qid, "query_token": token, "source_view": VIEW,
                "selection_policy": "latest-model-per-review", "start_date_kst": str(start),
                "end_date_kst": str(end), "objects": objects, "status": "COMPLETED"}
    # QueryExecutionId는 Iceberg snapshot_id가 아니다. 고정한 출력 파일을 읽는다.
    store.immutable(base + "/manifest.json", encode(manifest))
    return manifest
