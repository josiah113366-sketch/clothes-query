"""운영 어댑터의 실제 계산·S3 참조·완료 공개 실패 경계를 검증한다."""

import hashlib
import io
import json
from copy import deepcopy
from datetime import date

import pytest
from botocore.exceptions import ClientError

from pipelines.batch import execute, relocate, selected_date, validate
from pipelines.gold_a.tests.test_metrics_scenarios import make_example


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.fail_prefix = None
        self.mutate_key = None

    def put_object(self, Bucket, Key, Body, **kwargs):
        if self.fail_prefix and Key.startswith(self.fail_prefix):
            raise OSError("synthetic upload failure")
        existing = self.objects.get((Bucket, Key))
        if (kwargs.get("IfNoneMatch") == "*" and existing is not None
                or "IfMatch" in kwargs and kwargs["IfMatch"] != self.etag(existing or b"")):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Bucket, Key] = Body
        self.writes.append(Key)
        return {}

    @staticmethod
    def etag(body):
        return '"' + hashlib.sha256(body).hexdigest() + '"'

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        body = self.objects[Bucket, Key]
        return {"ETag": self.etag(body), "ContentLength": len(body)}

    def get_object(self, Bucket, Key, IfMatch=None):
        body = self.objects[Bucket, Key]
        if self.mutate_key == Key:
            body += b"\n"
        if IfMatch is not None and IfMatch != self.etag(body):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
        return {"Body": io.BytesIO(body)}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        rows = [{"Key": key, "Size": len(body), "ETag": self.etag(body)}
                for (bucket, key), body in sorted(self.objects.items())
                if bucket == Bucket and key.startswith(Prefix)]
        # 여러 페이지를 만들어 첫 페이지만 읽는 오류를 확인한다.
        for at in range(0, len(rows), 2):
            yield {"Contents": rows[at:at + 2]}


@pytest.fixture
def setup(tmp_path):
    sample = make_example(tmp_path / "fixture")
    s3 = MemoryS3()
    for path in sample["source"].rglob("*"):
        if path.is_file():
            s3.objects["test", "bronze/" + path.relative_to(sample["source"]).as_posix()] = path.read_bytes()
    return s3


def config(job="trade"):
    names = {"designs": "designs.jsonl", "variants": "variants.jsonl"}
    if job in {"trade", "funnels"}:
        names.update(orders="orders.jsonl", order_items="items.jsonl", payments="payments.jsonl")
    if job == "funnels":
        names["clicks"] = "clicks.jsonl"
    if job == "reviews":
        names.update(reviews="reviews/", mapping="mapping.jsonl", analysis="analysis.jsonl")
    return {"job": job, "output_root": "s3://test/", "input_complete": True,
            "inputs": {name: ["s3://test/bronze/" + path] for name, path in names.items()},
            **({"start_date": "2026-10-18", "end_date": "2026-10-19", "model_version": "demo.v1"}
               if job == "reviews" else {})}


@pytest.mark.parametrize("job", ["trade", "funnels", "reviews"])
def test_real_silver_gold_and_all_frozen_references_are_readable(setup, tmp_path, job):
    result = execute(config(job), setup, tmp_path / "work", "commit-test")
    assert result["status"] == "PASS" and result["coverage_status"] == "UNVERIFIED"
    current = json.loads(setup.objects["test", f"gold_a/runtime/{job}/current.json"])
    assert current["runtime_run_id"] == result["runtime_run_id"]
    assert len(result["inputs"]) >= 5
    if job == "trade":
        outputs = [body for (_, key), body in setup.objects.items()
                   if key.startswith("gold_a/runtime/trade/runs/") and key.endswith("order_sales_hourly.jsonl")]
        assert len(outputs) == 1
        assert sum(json.loads(line)["approved_amount"] for line in outputs[0].splitlines()) == 30000
    serialized = b"\n".join(body for (_, key), body in setup.objects.items() if not key.startswith("bronze/"))
    assert str(tmp_path).encode() not in serialized
    assert b"source_manifest" in serialized if job != "reviews" else b"model_version" in serialized
    # 고정 manifest·원본·결과의 S3 참조가 모두 실제 객체를 가리킨다.
    def check(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in {"request", "output_root"}:
                    check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif isinstance(value, str) and value.startswith("s3://") and not value.endswith("/"):
            bucket, key = value[5:].split("/", 1)
            assert (bucket, key) in setup.objects, value
    for (_, key), body in setup.objects.items():
        if not key.startswith("bronze/"):
            for line in body.decode().splitlines():
                check(json.loads(line))


def test_quality_failure_is_available_to_r6_and_keeps_previous_gold(setup, tmp_path):
    execute(config(), setup, tmp_path / "first", "c1")
    previous = setup.objects["test", "gold_a/runtime/trade/current.json"]
    orders = [json.loads(line) for line in setup.objects["test", "bronze/orders.jsonl"].splitlines()]
    for row in orders:
        row["total_amount"] += 10000
    setup.objects["test", "bronze/orders.jsonl"] = b"\n".join(json.dumps(row).encode() for row in orders)
    with pytest.raises(ValueError, match="Silver 품질 미완료"):
        execute(config(), setup, tmp_path / "bad", "c2")
    assert setup.objects["test", "gold_a/runtime/trade/current.json"] == previous
    last = json.loads(setup.objects["test", "silver/runtime/trade/current.json"])
    assert last["status"] == "INCOMPLETE"
    manifests = [json.loads(body) for (_, key), body in setup.objects.items()
                 if last["runtime_run_id"] in key and key.endswith("manifest.json")]
    trade = next(m for m in manifests if "order_amount_checks" in m.get("outputs", {}))
    rows = setup.objects["test", trade["outputs"]["order_amount_checks"].split("s3://test/", 1)[1]]
    checks = [json.loads(line) for line in rows.splitlines()]
    assert any(row["status"] == "MISMATCH" for row in checks)
    assert all(row["source_manifest"].startswith("s3://test/") and row["checked_at"] for row in checks)


def test_failed_gold_upload_keeps_latest_pointer_and_no_gold_completion(setup, tmp_path):
    execute(config(), setup, tmp_path / "first", "c1")
    previous = setup.objects["test", "gold_a/runtime/trade/current.json"]
    completed = [key for (_, key) in setup.objects if key.startswith("gold_a/runtime/trade/completed/")]
    setup.fail_prefix = "gold_a/runtime/trade/runs/"
    with pytest.raises(OSError, match="upload failure"):
        execute(config(), setup, tmp_path / "failed", "c2")
    assert setup.objects["test", "gold_a/runtime/trade/current.json"] == previous
    assert [key for (_, key) in setup.objects if key.startswith("gold_a/runtime/trade/completed/")] == completed


def test_changed_source_missing_input_and_download_limit_do_not_publish(setup, tmp_path):
    base = deepcopy(setup.objects)
    for variant in ("change", "missing", "limit"):
        setup.objects = deepcopy(base)
        request = config()
        setup.mutate_key = "bronze/orders.jsonl" if variant == "change" else None
        if variant == "missing":
            request["inputs"]["orders"] = ["s3://test/missing/"]
        if variant == "limit":
            request["max_download_bytes"] = 1
        with pytest.raises((ClientError, ValueError, FileNotFoundError)):
            execute(request, setup, tmp_path / variant, "c1")
        assert not any("/runtime/" in key for (_, key) in setup.objects)


def test_contract_requires_full_trade_inputs_and_review_utc_boundary():
    request = config()
    request["input_complete"] = False
    with pytest.raises(ValueError, match="input_complete"):
        validate(request)
    request = config("reviews")
    assert selected_date(request, "reviews", "year=2026/month=10/day=17/p.jsonl")
    assert not selected_date(request, "reviews", "year=2026/month=10/day=20/p.jsonl")
    request["start_date"] = str(date(2026, 10, 20))
    with pytest.raises(ValueError, match="시작"):
        validate(request)
    assert relocate("\\\\?\\C:\\work\\silver\\manifest.json", {"C:\\work\\silver": "s3://test/silver"}) == "s3://test/silver/manifest.json"


def test_member_job_exports_current_state_without_gold(tmp_path):
    s3 = MemoryS3()
    member = {"member_id": "00000000-4000-8000-0000-000000000011", "age_band": "30s",
              "gender": "F", "signup_channel": "app", "region_sigungu": "test-region",
              "marketing_consent": False, "status": "ACTIVE", "withdrawn_at": None,
              "signup_at": "2026-10-14T00:00:00Z", "created_at": "2026-10-14T00:00:00Z",
              "__op": "c", "__source_ts_ms": 100}
    s3.objects["test", "bronze/members-events/year=2026/month=10/day=14/members-events+0+00000.json"] = json.dumps(member).encode()
    request = {"job": "members", "output_root": "s3://test/", "through_date": "2026-10-14",
               "inputs": {"members": ["s3://test/bronze/members-events/"]}}
    result = execute(request, s3, tmp_path / "work", "c1")
    assert result["status"] == "PASS"
    assert not any(key.startswith("gold_a/") for (_, key) in s3.objects)
    rows = [json.loads(body) for (_, key), body in s3.objects.items() if key.endswith("members_current.jsonl")]
    assert len(rows) == 1 and rows[0]["status"] == "ACTIVE"
