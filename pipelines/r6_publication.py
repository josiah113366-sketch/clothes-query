"""완료된 Silver 금액 검사를 Athena에 공개한다. 원본 Parquet·업무 판정은 변경하지 않는다."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

UTC = timezone.utc
CHECK_COLUMNS = [
    ("order_id", "string"), ("check_name", "string"), ("check_version", "string"),
    ("status", "string"), ("order_total_amount", "bigint"), ("item_total_amount", "bigint"),
    ("amount_difference", "bigint"), ("checked_at", "timestamp"), ("checked_at_utc", "string"),
    ("source_manifest", "string"), ("format_rule_version", "string"),
]
RUN_COLUMNS = [
    ("run_id", "string"), ("completed_at", "timestamp"), ("status", "string"),
    ("quality_status", "string"), ("checked_at", "timestamp"), ("checked_at_utc", "string"),
    ("check_version", "string"), ("format_rule_version", "string"), ("row_count", "bigint"),
    ("coverage_status", "string"), ("source_manifest", "string"),
    ("source_manifest_sha256", "string"), ("result_location", "string"), ("code_ref", "string"),
]
STATUSES = {"PASS", "MISMATCH", "UNVERIFIED", "PENDING_REFERENCE", "ITEM_ERROR"}


class PublicationError(RuntimeError):
    """입력값·인증 정보를 오류 문장에 포함하지 않는 공개 오류."""


def schema(columns):
    types = {"string": pa.string(), "bigint": pa.int64(), "timestamp": pa.timestamp("ms")}
    return pa.schema([(name, types[kind]) for name, kind in columns])


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def utc(value):
    # Spark 원본 TIMESTAMP는 세션 UTC로 쓴다. 여기서만 저장값의 naive UTC를 해석한다.
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def millis(value):
    value = utc(value)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000, tzinfo=None)


def parquet(rows, columns):
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=schema(columns)), output, version="2.6",
                   coerce_timestamps="ms", allow_truncated_timestamps=False)
    return output.getvalue()


class S3Store:
    def __init__(self, root, client):
        parsed = urlsplit(root)
        if parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment:
            raise PublicationError("S3 출력 root가 필요합니다")
        if set(parsed.path.split("/")) & {"bronze", "bronze_v2", "ground_truth"}:
            raise PublicationError("원본·정답표 아래에는 공개 결과를 쓸 수 없습니다")
        self.bucket, self.prefix = parsed.netloc, parsed.path.lstrip("/").rstrip("/")
        self.root, self.client = root.rstrip("/"), client

    def key(self, name):
        return (self.prefix + "/" if self.prefix else "") + name

    def uri(self, name):
        return self.root + "/" + name

    def get(self, name):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self.key(name))
        except self.client.exceptions.NoSuchKey:
            return None, None
        try:
            return response["Body"].read(), response["ETag"]
        finally:
            response["Body"].close()

    def put(self, name, body, etag=None):
        from botocore.exceptions import ClientError

        try:
            result = self.client.put_object(Bucket=self.bucket, Key=self.key(name), Body=body,
                                            **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}))
            return result["ETag"]
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] in {409, 412}:
                raise PublicationError("공개 기록이 다른 실행에 의해 변경됐습니다; 덮어쓰지 않습니다") from None
            raise

    def immutable(self, name, body):
        current, _ = self.get(name)
        if current is not None:
            if current != body:
                raise PublicationError("동일 실행 ID의 고정 결과가 다릅니다")
            return
        self.put(name, body)

    def files(self, name):
        prefix = self.key(name).rstrip("/") + "/"
        return sorted(item["Key"][len(self.prefix) + 1 if self.prefix else 0:]
                      for page in self.client.get_paginator("list_objects_v2").paginate(
                          Bucket=self.bucket, Prefix=prefix)
                      for item in page.get("Contents", []) if item["Key"].endswith(".parquet"))


class GlueCatalog:
    def __init__(self, client, database, store):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", database):
            raise PublicationError("잘못된 Glue DB 이름입니다")
        self.client, self.database, self.store = client, database, store

    def validate(self):
        self.tables = {}
        for name, columns, partitions, location in [
            ("silver_runs", RUN_COLUMNS, [], "silver/runtime/trade/catalog/completed/"),
            ("order_amount_checks", CHECK_COLUMNS, [("run_id", "string")],
             "silver/runtime/trade/catalog-data/runs/"),
        ]:
            table = self.client.get_table(DatabaseName=self.database, Name=name)["Table"]
            descriptor = table["StorageDescriptor"]
            actual = [(c["Name"], c["Type"]) for c in descriptor["Columns"]]
            keys = [(c["Name"], c["Type"]) for c in table.get("PartitionKeys", [])]
            if (actual != columns or keys != partitions
                    or descriptor["Location"].rstrip("/") != self.store.uri(location).rstrip("/")
                    or "parquet" not in descriptor.get("InputFormat", "").lower()
                    or table.get("Parameters", {}).get("projection.enabled", "false").lower() == "true"):
                raise PublicationError("Glue 테이블 정의가 R6 공개 계약과 다릅니다")
            self.tables[name] = table

    def register(self, run_id, location, manifest_hash):
        descriptor = copy.deepcopy(self.tables["order_amount_checks"]["StorageDescriptor"])
        descriptor["Location"] = location
        expected = {"Values": [run_id], "StorageDescriptor": descriptor,
                    "Parameters": {"source_manifest_sha256": manifest_hash}}
        try:
            old = self.client.get_partition(DatabaseName=self.database, TableName="order_amount_checks",
                                            PartitionValues=[run_id])["Partition"]
        except self.client.exceptions.EntityNotFoundException:
            try:
                self.client.create_partition(DatabaseName=self.database, TableName="order_amount_checks",
                                             PartitionInput=expected)
                return
            except self.client.exceptions.AlreadyExistsException:
                old = self.client.get_partition(DatabaseName=self.database, TableName="order_amount_checks",
                                                PartitionValues=[run_id])["Partition"]
        if (old["StorageDescriptor"]["Location"].rstrip("/") != location.rstrip("/")
                or old.get("Parameters", {}).get("source_manifest_sha256") != manifest_hash
                or old["StorageDescriptor"]["Columns"] != descriptor["Columns"]):
            raise PublicationError("이미 등록된 실행 파티션이 다릅니다; 교체하지 않습니다")


class Publisher:
    STATE = "silver/runtime/trade/catalog-control/publication.json"

    def __init__(self, store, catalog, clock=lambda: datetime.now(UTC)):
        self.store, self.catalog, self.clock = store, catalog, clock

    def recover(self, stopped_owner):
        """운영자가 이전 게시자 종료를 확인한 뒤에만 명시적으로 소유권을 해제한다."""
        body, etag = self.store.get(self.STATE)
        state = json.loads(body) if body else {}
        if not stopped_owner or state.get("owner") != stopped_owner:
            raise PublicationError("복구 대상 공개 소유자가 일치하지 않습니다")
        state["owner"] = None
        self.store.put(self.STATE, encode(state), etag)

    def publish(self, run_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise PublicationError("잘못된 실행 ID입니다")
        self.catalog.validate()  # DB/DDL 준비 전에는 S3 공개 상태를 바꾸지 않는다.
        manifest_name = "silver/runtime/trade/runs/" + run_id + "/manifest.json"
        raw, _ = self.store.get(manifest_name)
        done, _ = self.store.get("silver/runtime/trade/completed/" + run_id + ".json")
        if raw is None or done is None or json.loads(raw) != json.loads(done):
            raise PublicationError("고정 Silver 결과와 완료 기록이 일치하지 않습니다")
        manifest = json.loads(raw)
        if manifest.get("run_id") != run_id or manifest.get("status") not in {"PASS", "INCOMPLETE"}:
            raise PublicationError("공개 가능한 Silver 완료 결과가 아닙니다")
        digest = hashlib.sha256(raw).hexdigest()
        projected = project_checks(self.store, manifest, manifest_name)
        # Silver 자체가 미완료/실패한 요청은 전역 공개 순서를 점유하지 않는다.
        body, etag = self.store.get(self.STATE)
        state = json.loads(body) if body else {"owner": None, "last_completed_at": None, "pending_run_id": None}
        if state.get("owner"):
            raise PublicationError("다른 게시자가 실행 중이거나 중단됐습니다; 종료 확인 후 소유권 복구가 필요합니다")
        if state.get("pending_run_id") not in {None, run_id}:
            raise PublicationError("이전 미완료 실행을 먼저 재개해야 합니다")
        state.update(owner=uuid4().hex, pending_run_id=run_id)
        etag = self.store.put(self.STATE, encode(state), etag)
        try:
            target = "silver/runtime/trade/catalog-data/runs/" + run_id + "/order_amount_checks/"
            completed = "silver/runtime/trade/catalog/completed/" + run_id + ".parquet"
            old, _ = self.store.get(completed)
            if old is not None:
                registered = pq.ParquetFile(io.BytesIO(old)).read().to_pylist()
                if (len(registered) != 1 or registered[0]["source_manifest_sha256"] != digest
                        or registered[0]["run_id"] != run_id):
                    raise PublicationError("이미 공개된 실행의 원본이 다릅니다")
                self.catalog.register(run_id, self.store.uri(target), digest)
                at = iso(utc(registered[0]["completed_at"]))
                if state.get("last_completed_at") is None or utc(at) > utc(state["last_completed_at"]):
                    state["last_completed_at"] = at
                state.update(pending_run_id=None, pending_completed_at=None)
                return {"run_id": run_id, "status": "ALREADY_PUBLISHED", "completed_at": at}
            self.store.immutable(target + "part-00000.parquet", parquet(projected, CHECK_COLUMNS))
            self.catalog.register(run_id, self.store.uri(target), digest)
            at = state.get("pending_completed_at")
            if not at:
                now = utc(self.clock())
                now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
                if state.get("last_completed_at"):
                    now = max(now, utc(state["last_completed_at"]) + timedelta(milliseconds=1))
                at = state["pending_completed_at"] = iso(now)
                etag = self.store.put(self.STATE, encode(state), etag)
            checked = utc(manifest["checked_at"])
            row = {"run_id": run_id, "completed_at": millis(at), "status": "COMPLETED",
                   "quality_status": manifest["status"], "checked_at": millis(checked),
                   "checked_at_utc": iso(checked), "check_version": manifest["check_version"],
                   "format_rule_version": manifest["format_rules"]["version"], "row_count": len(projected),
                   "coverage_status": manifest["coverage_status"], "source_manifest": self.store.uri(manifest_name),
                   "source_manifest_sha256": digest, "result_location": self.store.uri(target),
                   "code_ref": manifest["code_ref"]}
            self.store.immutable(completed, parquet([row], RUN_COLUMNS))  # 마지막에 완료 목록에 노출
            state.update(last_completed_at=at, pending_run_id=None, pending_completed_at=None)
            return {"run_id": run_id, "status": "COMPLETED", "row_count": len(projected), "completed_at": at}
        finally:
            # 예외 시 pending 실행을 남겨 다음 실행이 먼저 공개되는 것을 막는다.
            # 강제 종료라 finally가 실행되지 않았다면 명시적 recover 후 같은 run_id를 재개한다.
            state["owner"] = None
            self.store.put(self.STATE, encode(state), etag)


def project_checks(store, manifest, manifest_name):
    run_id = manifest["run_id"]
    source = "silver/runtime/trade/runs/" + run_id + "/order_amount_checks/"
    if manifest.get("outputs", {}).get("order_amount_checks", "").rstrip("/") != store.uri(source).rstrip("/"):
        raise PublicationError("금액 검사 입력 위치가 고정 실행과 다릅니다")
    files = store.files(source)
    if not files:
        raise PublicationError("금액 검사 Parquet이 없습니다; 정상 0건으로 취급하지 않습니다")
    rows = [row for name in files for row in pq.ParquetFile(io.BytesIO(store.get(name)[0])).read().to_pylist()]
    if len(rows) != manifest["output_counts"]["order_amount_checks"]:
        raise PublicationError("금액 검사 건수가 manifest와 다릅니다")
    projected, seen = [], set()
    for row in rows:
        if row.get("run_id") != run_id or row.get("source_manifest") != store.uri(manifest_name):
            raise PublicationError("금액 검사 실행 참조가 다릅니다")
        if any(not isinstance(row.get(k), str) or not row[k].strip()
               for k in ("order_id", "check_name", "check_version")) or row.get("status") not in STATUSES:
            raise PublicationError("금액 검사 키·상태가 잘못됐습니다")
        marker = (row["order_id"], row["check_name"])
        if marker in seen:
            raise PublicationError("같은 주문·검사가 한 실행에 중복됐습니다")
        seen.add(marker)
        checked = utc(row["checked_at"])
        if checked != utc(manifest["checked_at"]):
            raise PublicationError("행과 실행의 검사 시각이 다릅니다")
        for key in ("order_total_amount", "item_total_amount", "amount_difference"):
            if row.get(key) is not None and type(row[key]) is not int:
                raise PublicationError("금액은 정수 또는 NULL이어야 합니다")
        result = {key: row.get(key) for key, _ in CHECK_COLUMNS}
        result.update(checked_at=millis(checked), checked_at_utc=iso(checked),
                      format_rule_version=manifest["format_rules"]["version"])
        projected.append(result)
    return sorted(projected, key=lambda row: (row["order_id"], row["check_name"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-uri", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--recover-stopped-owner", help="이전 게시자 종료 확인 후 소유권 복구; 같은 요청만 재개")
    args = parser.parse_args()
    import boto3

    s3 = boto3.client("s3", region_name=args.region)
    parsed = urlsplit(args.config_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        parser.error("고정 실행 요청 S3 URI가 필요합니다")
    response = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    try:
        request = json.loads(response["Body"].read())
    finally:
        response["Body"].close()
    if request.get("job") == "reviews":
        print(encode({"status": "NOT_APPLICABLE", "job": "reviews"}).decode())
        return
    if request.get("job") not in {"trade", "funnels"}:
        raise PublicationError("지원하지 않는 작업입니다")
    store = S3Store(request["output_root"], s3)
    publisher = Publisher(store, GlueCatalog(boto3.client("glue", region_name=args.region), args.database, store))
    if args.recover_stopped_owner:
        publisher.recover(args.recover_stopped_owner)
    print(encode(publisher.publish(request["run_id"])).decode())


if __name__ == "__main__":
    main()
