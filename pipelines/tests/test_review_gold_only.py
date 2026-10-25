"""완료 리뷰 재사용 경계와 Gold 공개의 서로 다른 실행 ID를 검증한다."""
import hashlib
import json
from copy import deepcopy

import pytest

from pipelines.gold_a.reviews import _completed_review_source
from pipelines.gold_publication import GoldPublisher, PublicationError
from pipelines.r6_publication import encode
from pipelines.tests.test_final_runtime import Glue
from pipelines.tests.test_r6_publication import MemoryStore, read


def source_fixture(tmp_path):
    root = str(tmp_path)
    base = tmp_path / "silver/runtime/reviews/runs/old"
    base.mkdir(parents=True)
    silver = {"run_id": "old", "status": "PASS", "start_date_kst": "2026-10-19",
              "end_date_kst": "2026-10-19", "outputs": {k: str(base / k) for k in
              ("silver_reviews", "dq_results", "quarantined_records")}}
    product = {"run_id": "old", "status": "PASS", "outputs": {k: str(base / "products" / k) for k in
               ("silver_product_design", "silver_product_variant")}}
    (base / "products").mkdir()
    (base / "products/manifest.json").write_text(json.dumps(product), encoding="utf-8")
    (base / "manifest.json").write_text(json.dumps(silver), encoding="utf-8")
    done = tmp_path / "silver/runtime/reviews/completed/old.json"
    done.parent.mkdir()
    done.write_text(json.dumps(silver), encoding="utf-8")
    config = {"run_id": "new", "output_root": root, "silver_manifest": str(base / "manifest.json"),
              "silver_manifest_sha256": hashlib.sha256((base / "manifest.json").read_bytes()).hexdigest(),
              "start_date": "2026-10-19", "end_date": "2026-10-19"}
    return config, base, done


def test_fixed_completed_pass_source_and_existing_products(tmp_path):
    config, base, done = source_fixture(tmp_path)
    before = {p: p.read_bytes() for p in (base / "manifest.json", done, base / "products/manifest.json")}
    silver, product, *_ = _completed_review_source(config)
    assert silver["run_id"] == product["run_id"] == "old"
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("fault", ["hash", "incomplete", "completion", "same_id", "date", "product", "path"])
def test_invalid_sources_are_rejected(tmp_path, fault):
    config, base, done = source_fixture(tmp_path)
    if fault == "hash":
        config["silver_manifest_sha256"] = "0" * 64
    elif fault == "same_id":
        config["run_id"] = "old"
    elif fault == "date":
        config["start_date"] = "2026-10-18"
    elif fault == "completion":
        done.write_text("{}", encoding="utf-8")
    elif fault == "product":
        (base / "products/manifest.json").write_text('{"run_id":"other","status":"PASS"}', encoding="utf-8")
    else:
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        if fault == "incomplete":
            manifest["status"] = "INCOMPLETE"
        else:
            manifest["outputs"]["silver_reviews"] = str(base / "elsewhere")
        body = json.dumps(manifest)
        (base / "manifest.json").write_text(body, encoding="utf-8")
        done.write_text(body, encoding="utf-8")
        config["silver_manifest_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    with pytest.raises(ValueError):
        _completed_review_source(config)


def test_gold_registry_preserves_reused_silver_id_and_rejects_changed_source():
    store = MemoryStore()
    glue = Glue(store)
    base = "gold_a/runtime/reviews/runs/new"
    name = "review_product_daily"
    schema = {"fields": [{"name": "review_count", "type": "long"}]}
    glue.tables[name + "_runs"] = {"StorageDescriptor": {
        "Columns": [{"Name": "review_count", "Type": "bigint"}],
        "Location": store.uri("gold_a/runtime/reviews/runs/"), "InputFormat": "parquet"},
        "PartitionKeys": [{"Name": "run_id", "Type": "string"}]}
    silver_key = "silver/runtime/reviews/runs/old/manifest.json"
    original = encode({"run_id": "old", "status": "PASS"})
    store.data[silver_key] = original
    store.data["silver/runtime/reviews/completed/old.json"] = original
    manifest = {"run_id": "new", "status": "PASS", "gold_only": True, "silver_run_id": "old",
                "silver_manifest": store.uri(silver_key), "silver_manifest_sha256": hashlib.sha256(original).hexdigest(),
                "outputs": {name: store.uri(base + "/" + name)}, "schemas": {name: schema},
                "output_counts": {name: 1}}
    store.data[base + "/manifest.json"] = encode(manifest)
    store.data["gold_a/runtime/reviews/completed/new.json"] = encode(manifest)
    store.data[base + "/" + name + "/part-0.parquet"] = b"presence"
    publisher = GoldPublisher(store, glue, "gold_a", "reviews")
    publisher.publish("new")
    row = read(store.data["gold_a/runtime/reviews/catalog/completed/new.parquet"])[0]
    assert row["run_id"] == "new" and row["silver_run_id"] == "old"
    assert row["silver_manifest"] == store.uri(silver_key)
    assert publisher.publish("new")["status"] == "COMPLETED"
    before = deepcopy(store.data)
    store.data[silver_key] = encode({"run_id": "old", "status": "INCOMPLETE"})
    with pytest.raises(PublicationError):
        publisher.publish("new")
    assert store.data["gold_a/runtime/reviews/catalog/completed/new.parquet"] == before[
        "gold_a/runtime/reviews/catalog/completed/new.parquet"]
