import json
import re
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[2] / "connectors"
SINK_PATH = CONNECTORS / "member-s3-sink.json"
SOURCE_PATH = CONNECTORS / "member-source.json"
SECRET_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}")


def _sink() -> dict[str, str]:
    return json.loads(SINK_PATH.read_text(encoding="utf-8"))


def test_topic_matches_source_routing() -> None:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    assert _sink()["topics"] == source["transforms.route.replacement"]


def test_daily_utc_hive_partition_by_record_time() -> None:
    config = _sink()
    assert config["partitioner.class"].endswith("TimeBasedPartitioner")
    assert config["timezone"] == "UTC"
    assert config["path.format"] == "'dt'=YYYY-MM-dd"
    assert config["partition.duration.ms"] == "86400000"
    assert config["timestamp.extractor"] == "Record"
    assert config["topics.dir"] == "bronze"


def test_json_lines_without_schema() -> None:
    config = _sink()
    assert config["format.class"].endswith("format.json.JsonFormat")
    assert config["value.converter.schemas.enable"] == "false"
    assert config["key.converter.schemas.enable"] == "false"


def test_bucket_and_region_come_from_environment() -> None:
    config = _sink()
    assert config["s3.bucket.name"] == "${env:S3_BUCKET}"
    assert config["s3.region"] == "${env:AWS_REGION}"


def test_no_credentials_in_connector_file() -> None:
    text = SINK_PATH.read_text(encoding="utf-8")
    config = _sink()
    assert not any("access.key" in key or "secret" in key for key in config)
    assert not SECRET_PATTERN.search(text)
