"""클릭 식별·상품 연결·공통 로컬 입출력을 실제 오류 사례로 확인한다."""
import json
from pathlib import Path

from pipelines.silver.clicks import build_clicks, run as run_clicks
from pipelines.silver.products import build_products, run as run_products


def click(identifier="E-1", **changes):
    return {"event_id": identifier, "event_type": "view", "member_id": "M-test",
            "article_id": "0000000001", "session_id": "S-test",
            "event_time": "2026-10-13T15:10:00+00:00", **changes}


def design(code=100, **changes):
    return {"product_code": code, "product_type_no": 1, "product_type_name": "type-test",
            "product_group_name": "group-test", "garment_group_no": 2,
            "garment_group_name": "garment-test", "index_group_no": 3,
            "index_group_name": "index-test", "design_price": 1000, **changes}


def variant(identifier="0000000001", **changes):
    return {"article_id": identifier, "product_code": 100, "prod_name": "product-test",
            "colour_group_code": 1, "colour_group_name": "colour-test",
            "graphical_appearance_no": 2, "graphical_appearance_name": "pattern-test",
            "price": 1000, **changes}


def test_click_repeated_visit_is_not_duplicate_and_conflicts_are_not_selected():
    events = [click(), click(), click("E-2"), click("E-conflict"),
              click("E-conflict", event_type="cart_add"), click("E-bad", event_type="purchase")]
    result = build_clicks(events)
    assert [row["event_id"] for row in result["click_events"]] == ["E-1", "E-2"]
    assert result["click_events"][0]["event_date_kst"] == "2026-10-14"
    assert result["click_events"][0]["article_id"] == "0000000001"
    quality = result["dq_results"][0]
    assert (quality["accepted_count"], quality["duplicate_count"], quality["quarantined_count"]) == (2, 1, 3)
    assert quality["conflict_count"] == 2
    assert quality["status"] == "INCOMPLETE"
    assert "member_id" not in result["quarantined_records"][0]
    assert result == build_clicks(events)


def test_product_design_conflict_and_missing_reference_block_only_affected_products():
    designs = [design(), design(), design(200), design(200, design_price=2000), design(300, design_price="bad")]
    variants = [variant(), variant(), variant("0000000002", product_code=200),
                variant("0000000003", product_code=999), variant("0000000004", product_code=300)]
    result = build_products(designs, variants)
    assert [row["product_code"] for row in result["silver_product_design"]] == [100]
    assert [row["article_id"] for row in result["silver_product_variant"]] == ["0000000001"]
    issues = {row["record_key"]: row for row in result["quarantined_records"] if row["source_dataset"] == "product_variant"}
    assert issues["0000000002"]["category"] == "DEPENDENCY_BLOCKED"
    assert issues["0000000003"]["category"] == "PENDING_REFERENCE"
    assert issues["0000000004"]["category"] == "DEPENDENCY_BLOCKED"
    for summary in result["dq_results"]:
        assert summary["input_count"] == sum(summary[key] for key in (
            "accepted_count", "duplicate_count", "quarantined_count",
        ))


def test_product_key_conflicts_and_missing_required_fields():
    rows = [variant(), variant(price=2000), variant("0000000002", colour_group_name=None),
            variant("0000000003", price=True), variant("0000000004")]
    result = build_products([design()], rows)
    assert [row["article_id"] for row in result["silver_product_variant"]] == ["0000000004"]
    assert result["dq_results"][1]["conflict_count"] == 2
    assert build_products([], [])["silver_product_design"] == []
    assert build_clicks([])["click_events"] == []


def test_local_snapshots_keep_source_locations_and_publish_complete_result_sets(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    clicks = inputs / "clicks.jsonl"
    clicks.write_text(json.dumps(click()) + "\nbad-json\n", encoding="utf-8")
    first = run_clicks(str(clicks), str(tmp_path / "click-output"))
    second = run_clicks(str(clicks), str(tmp_path / "click-output"))
    assert first["output_counts"] == second["output_counts"]
    issues = [json.loads(line) for line in Path(second["outputs"]["quarantined_records"]).read_text(encoding="utf-8").splitlines()]
    assert issues[0]["source_line"] == 2
    assert issues[0]["source_file"] == str(clicks.resolve())
    designs, variants = inputs / "designs.jsonl", inputs / "variants.jsonl"
    designs.write_text(json.dumps(design()) + "\n", encoding="utf-8")
    variants.write_text(json.dumps(variant()) + "\n", encoding="utf-8")
    manifest = run_products(str(designs), str(variants), str(tmp_path / "product-output"))
    assert manifest["status"] == "PASS"
    assert manifest["output_counts"] == {
        "silver_product_design": 1, "silver_product_variant": 1,
        "quarantined_records": 0, "dq_results": 2,
    }
    assert json.loads(Path(manifest["manifest_path"]).read_text(encoding="utf-8")) == manifest
