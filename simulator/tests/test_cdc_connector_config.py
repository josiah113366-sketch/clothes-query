import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "connectors" / "member-source.json"
BRONZE_COLUMNS = {
    "member_id",
    "signup_at",
    "signup_channel",
    "gender",
    "age_band",
    "region_sigungu",
    "marketing_consent",
    "status",
    "withdrawn_at",
    "created_at",
}
PII_COLUMNS = {"name", "email", "phone", "birth_date", "password_hash"}


def _config() -> dict[str, str]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_include_list_is_exactly_the_ten_bronze_columns() -> None:
    config = _config()
    columns = config["column.include.list"].split(",")
    assert all(c.startswith("public.members.") for c in columns)
    names = {c.removeprefix("public.members.") for c in columns}
    assert len(columns) == len(names) == 10
    assert names == BRONZE_COLUMNS
    assert names.isdisjoint(PII_COLUMNS)


def test_no_exclude_list_and_single_table() -> None:
    config = _config()
    assert "column.exclude.list" not in config
    assert config["table.include.list"] == "public.members"
    assert "members_archive" not in json.dumps(config)


def test_password_is_not_plaintext() -> None:
    config = _config()
    assert re.fullmatch(r"\$\{env:[A-Z_]+\}", config["database.password"])


def test_route_turns_data_topic_into_member_events() -> None:
    config = _config()
    data_topic = f"{config['topic.prefix']}.public.members"
    assert re.fullmatch(config["transforms.route.regex"], data_topic)
    assert config["transforms.route.replacement"] == "members-events"
    # 하트비트 토픽은 라우팅되지 않고, unwrap도 데이터 토픽에만 적용된다
    heartbeat = f"__debezium-heartbeat.{config['topic.prefix']}"
    assert not re.fullmatch(config["transforms.route.regex"], heartbeat)
    assert config["transforms.unwrap.predicate"] == "isData"
    assert re.fullmatch(config["predicates.isData.pattern"], data_topic)
    assert not re.fullmatch(config["predicates.isData.pattern"], heartbeat)


def test_fixed_values() -> None:
    config = _config()
    assert config["name"] == "member-source"
    assert (config["slot.name"], config["publication.name"]) == ("member_slot", "member_pub")
    assert config["publication.autocreate.mode"] == "filtered"
    assert config["snapshot.mode"] == "initial"
    assert config["heartbeat.interval.ms"] == "10000"
    assert config["value.converter.schemas.enable"] == "false"
    assert config["key.converter.schemas.enable"] == "false"
