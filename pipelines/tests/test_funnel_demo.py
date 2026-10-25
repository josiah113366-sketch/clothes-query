"""시연 범위 고정·운영 공개 차단·측정 경계를 검증한다. AWS 접속 없음."""
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pipelines.funnel_demo import (
    Measurements,
    encode,
    load_selection,
    relative_uri,
    validate_request,
)
from pipelines.funnel_demo_prepare import scan_click_object


def request(tmp_path):
    return {"job": "funnels", "mode": "demo", "run_id": "demo-1", "output_root": (tmp_path / "result").as_posix(),
            "selection_manifest": (tmp_path / "selection.json").as_posix(), "selection_sha256": "a" * 64}


def test_rejects_operating_output_prefix_and_scope_escape(tmp_path):
    config = request(tmp_path)
    for output in ("s3://bucket", "s3://bucket/gold_a/runtime/funnels", "s3://bucket/bronze_v2", "s3://bucket/pipelines/demo/funnels/../x"):
        with pytest.raises(ValueError):
            validate_request({**config, "output_root": output})
    for path in ("../source.json", "/source", "x\\source", "x/../source"):
        with pytest.raises(ValueError):
            relative_uri(config["selection_manifest"], path)
    assert validate_request(config).endswith("/runs/demo-1")


def test_reads_selected_session_across_fixed_files_and_preserves_scope():
    class S3:
        def get_object(self, Bucket, Key, IfMatch):
            assert IfMatch == '"fixed"'
            return {"Body": io.BytesIO(files[Key])}
    files = {"day1": encode({"session_id": "selected", "event_type": "view"}) + b"\n",
             "day2": encode({"session_id": "selected", "event_type": "cart_add"}) + b"\n" +
                     encode({"session_id": "other", "event_type": "view"}) + b"\n"}
    results = [scan_click_object({"uri": "s3://bucket/" + key, "etag": '"fixed"', "size": len(body)}, {"selected"}, S3())
               for key, body in files.items()]
    assert [row["event_type"] for result in results for _, row in result[1]] == ["view", "cart_add"]
    assert sum(result[2] for result in results) == 3


def test_changed_fixed_input_is_rejected(tmp_path):
    config = request(tmp_path)
    source = tmp_path / "source.json"
    source.write_bytes(encode({"run_id": "old", "status": "INCOMPLETE"}))
    objects = {}
    for name in ("clicks", "orders", "items", "payments", "checks", "order_quality", "designs", "variants", "expected"):
        path = tmp_path / (name + ".data")
        path.write_bytes(b"fixed")
        objects[name] = {"file": path.name, "size": 5, "sha256": hashlib.sha256(b"fixed").hexdigest()}
    selection = {"version": "funnel-demo.v1", "coverage_status": "FIXED_SOURCE_INVENTORY_COMPLETE",
                 "session_ids": ["session"], "selected_order_quality": "PASS", "objects": objects,
                 "source_trade": {"manifest": source.as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                  "run_id": "old", "quality_status": "INCOMPLETE"}}
    raw = encode(selection)
    (tmp_path / "selection.json").write_bytes(raw)
    config["selection_sha256"] = hashlib.sha256(raw).hexdigest()
    result, _ = load_selection(config)
    assert result["source_trade"]["quality_status"] == "INCOMPLETE"
    (tmp_path / "clicks.data").write_bytes(b"changed")
    with pytest.raises(ValueError, match="변경"):
        load_selection(config)


def test_stage_times_are_individual_and_failed_stage_stays_failed():
    ticks = iter([0, 1, 3, 3, 4, 8, 8])
    clock = Measurements(lambda: next(ticks))
    with clock.stage("first"):
        pass
    with pytest.raises(RuntimeError), clock.stage("failed"):
        raise RuntimeError("expected")
    assert clock.stages == [{"stage": "first", "status": "SUCCESS", "seconds": 2, "cumulative_seconds": 3},
                            {"stage": "failed", "status": "FAILED", "seconds": 4, "cumulative_seconds": 8}]


@pytest.mark.parametrize("module", ["pipelines.r6_publication", "pipelines.gold_publication"])
def test_demo_publication_does_not_create_glue_or_operating_publisher(tmp_path, module):
    import importlib
    target = importlib.import_module(module)
    config = {**request(tmp_path), "output_root": "s3://bucket/pipelines/demo/funnels", "selection_manifest": "s3://bucket/selection.json"}
    def client(name, **kwargs):
        assert name == "s3", "시연 공개 태스크는 Glue를 호출하면 안 됩니다"
        return SimpleNamespace(get_object=lambda **kwargs: {"Body": io.BytesIO(json.dumps(config).encode())})
    with patch("boto3.client", side_effect=client), patch("sys.argv", [module, "--config-uri", "s3://bucket/request.json", "--database", "gold_a"]), patch(
            "pipelines.funnel_demo.verify_complete", return_value={"status": "DEMO_VERIFIED"}) as verify:
        target.main()
        if module.endswith("gold_publication"):
            verify.assert_called_once_with(config)
