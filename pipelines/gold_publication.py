"""완료 Gold A 결과만 run_id 파티션과 완료 목록으로 공개한다."""
import argparse
import copy
import hashlib
import io
import json
import re
from datetime import datetime, timedelta
from uuid import uuid4

import pyarrow.parquet as pq

from pipelines.r6_publication import (
    UTC,
    PublicationError,
    S3Store,
    encode,
    iso,
    millis,
    parquet,
    utc,
)

RUN_COLUMNS = [("run_id", "string"), ("completed_at", "timestamp"), ("status", "string"),
               ("quality_status", "string"), ("source_manifest", "string"),
               ("source_manifest_sha256", "string"), ("silver_run_id", "string"),
               ("silver_manifest", "string"), ("products_manifest", "string"),
               ("silver_clicks_manifest", "string"), ("previous_run_id", "string"),
               ("held_scope_count", "bigint"), ("available_tables_json", "string"), ("code_ref", "string")]
METRICS = {"trade": {"order_sales_hourly", "product_sales_daily", "refresh_holds"},
           "funnels": {"funnel_session_product", "funnel_daily", "refresh_holds"},
           "reviews": {"review_product_daily", "review_aspect_daily"}}
TYPES = {"string": "string", "long": "bigint", "integer": "int", "boolean": "boolean",
         "double": "double", "date": "date"}


class GoldPublisher:
    def __init__(self, store, glue, database, channel, clock=lambda: datetime.now(UTC)):
        if channel not in METRICS or not re.fullmatch(r"[a-z][a-z0-9_]*", database):
            raise PublicationError("Gold 공개 DB·channel 오류")
        self.store, self.glue, self.database, self.channel, self.clock = store, glue, database, channel, clock
        self.base = f"gold_a/runtime/{channel}"
        self.state_key = self.base + "/catalog-control/publication.json"

    def table(self, name, columns, partitions):
        table = self.glue.get_table(DatabaseName=self.database, Name=name)["Table"]
        expected_root = ("gold_a/catalog/" if name == "gold_runs" else "gold_a/catalog/holds/"
                         if name == "refresh_holds_runs" else self.base + "/runs/")
        if ([(x["Name"], x["Type"]) for x in table["StorageDescriptor"]["Columns"]] != columns
                or [(x["Name"], x["Type"]) for x in table.get("PartitionKeys", [])] != partitions
                or "parquet" not in table["StorageDescriptor"].get("InputFormat", "").lower()
                or table["StorageDescriptor"]["Location"].rstrip("/") != self.store.uri(expected_root).rstrip("/")
                or table.get("Parameters", {}).get("projection.enabled", "false").lower() == "true"):
            raise PublicationError("Gold Glue 정의가 실행 스키마와 다릅니다: " + name)
        return table

    def recover(self, stopped_owner):
        body, etag = self.store.get(self.state_key)
        state = json.loads(body) if body else {}
        if not stopped_owner or state.get("owner") != stopped_owner:
            raise PublicationError("복구 대상 Gold 공개 소유자가 다릅니다")
        state["owner"] = None
        self.store.put(self.state_key, encode(state), etag)

    def register(self, name, table, values, location, digest=None):
        descriptor = copy.deepcopy(table["StorageDescriptor"])
        descriptor["Location"] = location
        expected = {"Values": values, "StorageDescriptor": descriptor,
                    "Parameters": {"source_manifest_sha256": digest} if digest else {}}
        try:
            old = self.glue.get_partition(DatabaseName=self.database, TableName=name,
                                           PartitionValues=values)["Partition"]
        except self.glue.exceptions.EntityNotFoundException:
            try:
                self.glue.create_partition(DatabaseName=self.database, TableName=name, PartitionInput=expected)
                return
            except self.glue.exceptions.AlreadyExistsException:
                old = self.glue.get_partition(DatabaseName=self.database, TableName=name,
                                               PartitionValues=values)["Partition"]
        if (old["StorageDescriptor"]["Location"].rstrip("/") != location.rstrip("/")
                or old["StorageDescriptor"]["Columns"] != descriptor["Columns"]
                or (digest and old.get("Parameters", {}).get("source_manifest_sha256") != digest)):
            raise PublicationError("기존 Gold 파티션이 다릅니다; 교체하지 않습니다")

    def publish(self, run_id, advertise=True):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise PublicationError("Gold run_id 오류")
        source = self.base + f"/runs/{run_id}/manifest.json"
        raw, _ = self.store.get(source)
        done, _ = self.store.get(self.base + f"/completed/{run_id}.json")
        if raw is None or done is None or json.loads(raw) != json.loads(done):
            raise PublicationError("고정 Gold 결과와 완료 기록이 다릅니다")
        manifest = json.loads(raw)
        names = set(manifest.get("outputs", {}))
        required = METRICS[self.channel] - ({"review_aspect_daily"} if self.channel == "reviews" else set())
        if (manifest.get("run_id") != run_id or manifest.get("status") not in {"PASS", "PARTIAL"}
                or not required <= names or names - METRICS[self.channel]):
            raise PublicationError("Gold 완료 결과·공개 테이블 오류")
        registry = self.table("gold_runs", RUN_COLUMNS, [("channel", "string")])
        tables = {}
        for name in sorted(names):
            expected_uri = self.store.uri(self.base + f"/runs/{run_id}/{name}")
            if manifest["outputs"][name].rstrip("/") != expected_uri:
                raise PublicationError("Gold 출력이 고정 실행 경로 밖에 있습니다")
            if not self.store.files(self.base + f"/runs/{run_id}/{name}"):
                raise PublicationError("Gold Parquet 없음; 정상 0건으로 간주하지 않습니다")
            try:
                columns = [(field["name"], TYPES[field["type"]]) for field in manifest["schemas"][name]["fields"]]
            except (KeyError, TypeError):
                raise PublicationError("Athena 직접 공개 불가 타입; 별도 투영이 필요합니다") from None
            parts = [("channel", "string"), ("run_id", "string")] if name == "refresh_holds" else [("run_id", "string")]
            tables[name] = self.table(name + "_runs", columns, parts)
        digest = hashlib.sha256(raw).hexdigest()
        body, etag = self.store.get(self.state_key)
        state = json.loads(body) if body else {"owner": None, "pending_run_id": None, "last_completed_at": None}
        if state.get("owner") or state.get("pending_run_id") not in {None, run_id}:
            raise PublicationError("다른 Gold 공개 실행 중 또는 이전 미완료 실행 재개 필요")
        state.update(owner=uuid4().hex, pending_run_id=run_id)
        etag = self.store.put(self.state_key, encode(state), etag)
        try:
            for name, table in tables.items():
                values = [self.channel, run_id] if name == "refresh_holds" else [run_id]
                self.register(name + "_runs", table, values, manifest["outputs"][name], digest)
            if not advertise:
                # Backfill drafts remain directly queryable by run_id, but do
                # not replace the dashboard's latest complete input inventory.
                state.update(pending_run_id=None, pending_completed_at=None)
                return {"channel": self.channel, "run_id": run_id, "status": "STAGED"}
            registry_path = self.base + "/catalog/completed/"
            self.register("gold_runs", registry, [self.channel], self.store.uri(registry_path))
            completed_key = registry_path + run_id + ".parquet"
            old, _ = self.store.get(completed_key)
            if old:
                records = pq.ParquetFile(io.BytesIO(old)).read().to_pylist()
                if len(records) != 1 or records[0]["source_manifest_sha256"] != digest:
                    raise PublicationError("이미 공개한 Gold 실행 내용이 다릅니다")
                at = iso(utc(records[0]["completed_at"]))
            else:
                at = state.get("pending_completed_at")
                if not at:
                    now = utc(millis(self.clock()))
                    if state.get("last_completed_at"):
                        now = max(now, utc(state["last_completed_at"]) + timedelta(milliseconds=1))
                    at = state["pending_completed_at"] = iso(now)
                    etag = self.store.put(self.state_key, encode(state), etag)
                row = {key: manifest.get(key) for key, _ in RUN_COLUMNS}
                row.update(run_id=run_id, completed_at=millis(at), status="COMPLETED",
                           quality_status=manifest["status"], source_manifest=self.store.uri(source),
                           source_manifest_sha256=digest, silver_run_id=run_id,
                           held_scope_count=len(manifest.get("held_scopes", [])),
                           available_tables_json=json.dumps(manifest["output_counts"], sort_keys=True))
                self.store.immutable(completed_key, parquet([row], RUN_COLUMNS))
            if not state.get("last_completed_at") or utc(at) > utc(state["last_completed_at"]):
                state["last_completed_at"] = at
            state.update(pending_run_id=None, pending_completed_at=None)
            return {"channel": self.channel, "run_id": run_id, "status": "COMPLETED", "completed_at": at}
        finally:
            state["owner"] = None
            self.store.put(self.state_key, encode(state), etag)


def main():
    from urllib.parse import urlsplit

    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-uri", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--recover-stopped-owner")
    parser.add_argument("--athena-workgroup", default="")
    parser.add_argument("--athena-output", default="")
    args = parser.parse_args()
    s3 = boto3.client("s3", region_name="ap-northeast-1")
    parsed = urlsplit(args.config_uri)
    response = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    try:
        config = json.loads(response["Body"].read())
    finally:
        response["Body"].close()
    if config.get("mode") == "demo":
        from pipelines.funnel_demo import verify_complete
        print(encode(verify_complete(config)).decode())
        return
    if config.get("mode") == "incremental" and (not args.athena_workgroup or not args.athena_output.startswith("s3://")):
        raise PublicationError("증분 공개에는 Athena 검증 작업그룹·결과 경로가 필요합니다")
    store = S3Store(config["output_root"], s3)
    publisher = GoldPublisher(store, boto3.client("glue", region_name="ap-northeast-1"),
                              args.database, config["job"])
    if args.recover_stopped_owner:
        publisher.recover(args.recover_stopped_owner)
    advertise = True
    if config.get("mode") == "incremental":
        from pipelines.funnel_demo import read_bytes
        manifest = json.loads(read_bytes(config["output_root"].rstrip("/") +
            "/gold_a/runtime/funnels/runs/" + config["run_id"] + "/manifest.json"))
        advertise = manifest["batch"]["remaining_files"] == 0
    print(encode(publisher.publish(config["run_id"], advertise=advertise)).decode())
    if config.get("mode") == "incremental":
        from pipelines.funnel_control import acknowledge
        print(encode(acknowledge(config, args.database, args.athena_workgroup, args.athena_output)).decode())


if __name__ == "__main__":
    main()
