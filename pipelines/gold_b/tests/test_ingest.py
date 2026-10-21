"""적재 잡 시험. Spark 없이 1분 묶음 처리(write_batch)와 설정을 확인한다.

Spark 연결(build_query)은 이 PC에서 Spark가 뜨지 않아 시험하지 않는다.
형식 검사는 아직 없어서 재처리 시험과 같은 가짜(SampleChecker)를 쓴다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("pyarrow")

from pipelines.gold_b.jobs.streaming_ingest import (CONFIG_PATH, Config, ConfigError, Settings,  # noqa: E402
                                                    kafka_options, load_config, write_batch)
from pipelines.gold_b.ledger import EVENT_TIME, LocalStore, hour_of  # noqa: E402
from test_reprocess import SampleChecker, comparable, sample_messages, streamed_rows  # noqa: E402

LOADED_AT = datetime(2026, 10, 21, 6, 31)
TABLES = ("topic_messages", "payment_events", "malformed_events")


def all_rows(store: LocalStore, table: str) -> list[dict]:
    root = store._root / table   # 시험에서만 폴더를 훑는다
    return [row for path in sorted(root.rglob("*.parquet"))
            for row in store.read(path.relative_to(store._root).as_posix(), table)]


def test_batch_rows_go_to_their_hour_folders(tmp_path):
    store, checker = LocalStore(tmp_path), SampleChecker()

    summary = write_batch(sample_messages(), checker=checker, store=store, loaded_at=LOADED_AT)

    expected = streamed_rows(checker, LOADED_AT)
    for table in TABLES:
        rows = all_rows(store, table)
        assert comparable(rows) == comparable(expected[table]), table
        assert {r["loaded_at"] for r in rows} == {LOADED_AT}
    assert summary["rows"] == {table: len(expected[table]) for table in TABLES}
    # 파일은 (표, 이벤트 시각의 시간 폴더)마다 하나: topic_messages 05·06시, payment_events 06시, malformed_events 06시
    assert summary["files"] == 4
    member = next(r for r in all_rows(store, "topic_messages") if r["topic"] == "members-events" and r["kafka_offset"] == 3000)
    assert hour_of(member[EVENT_TIME["topic_messages"]]) == datetime(2026, 10, 21, 5)


def test_same_batch_again_overwrites_and_next_batch_adds(tmp_path):
    """Spark가 끝내지 못한 묶음을 다시 처리하면 같은 파일을 덮어쓴다. 다음 묶음은 새 파일로 쌓인다."""
    store, checker = LocalStore(tmp_path), SampleChecker()
    messages = sample_messages()
    first, second = messages[:12], messages[12:]

    write_batch(first, checker=checker, store=store, loaded_at=LOADED_AT)
    files = sorted(p.name for p in tmp_path.rglob("*.parquet"))
    write_batch(first, checker=checker, store=store, loaded_at=datetime(2026, 10, 21, 6, 32))
    assert sorted(p.name for p in tmp_path.rglob("*.parquet")) == files
    write_batch(second, checker=checker, store=store, loaded_at=datetime(2026, 10, 21, 6, 33))

    expected = streamed_rows(checker)
    for table in TABLES:
        assert comparable(all_rows(store, table)) == comparable(expected[table]), table


def test_settings_and_kafka_options():
    with pytest.raises(ConfigError):
        Settings.from_env({"GOLD_B_LEDGER_ROOT": "s3://bucket-x/gold_b"})
    settings = Settings.from_env({"GOLD_B_LEDGER_ROOT": "s3://bucket-x/gold_b", "GOLD_B_CHECKPOINT": "s3a://bucket-x/cp",
                                  "KAFKA_BOOTSTRAP": "broker-x:9092"})
    assert "bucket-x" not in repr(settings) and "broker-x" not in repr(settings)
    options = kafka_options(settings, Config(topics=("payments", "clickstream")))
    assert options["subscribe"] == "payments,clickstream"
    assert (options["startingOffsets"], options["failOnDataLoss"], options["kafka.allow.auto.create.topics"]) == (
        "earliest", "false", "false")
    assert not any(key.startswith("kafka.ssl.") for key in options)


def test_config_file():
    pytest.importorskip("yaml")
    config = load_config(CONFIG_PATH)
    assert config.topics == ("payments", "orders", "order-items", "members-events", "clickstream", "reviews.raw")
    assert (config.trigger_seconds, config.starting_offsets) == (60, "earliest")
