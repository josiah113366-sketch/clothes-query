"""적재 잡 시험. Spark 없이 1분 묶음 처리(write_batch)와 설정을 확인한다.

Spark 연결(build_query)은 이 PC에서 Spark가 뜨지 않아 시험하지 않는다 (실행 입구 시험은 가짜 쿼리로 바꿔 본다).
묶음 시험은 재처리 시험과 같은 가짜(SampleChecker)를 쓰고, 실제 형식 검사기 연결은 따로 확인한다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("pyarrow")

from pipelines.gold_b.jobs.streaming_ingest import (CONFIG_PATH, Config, ConfigError, Settings,  # noqa: E402
                                                    kafka_options, load_config, main, topic_pattern, write_batch)
from pipelines.gold_b.ledger import EVENT_TIME, LocalStore, hour_of  # noqa: E402
from test_ddl import load_samples  # noqa: E402
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
    assert options["subscribePattern"] == r"^(payments|clickstream)$"
    assert "subscribe" not in options   # 이름 목록으로 받으면 없는 토픽 하나에 쿼리가 실패한다
    assert (options["startingOffsets"], options["failOnDataLoss"], options["kafka.allow.auto.create.topics"]) == (
        "earliest", "false", "false")
    assert not any(key.startswith("kafka.ssl.") for key in options)


def test_topic_pattern_matches_only_exact_names():
    import re
    pattern = re.compile(topic_pattern(("order-items", "reviews.raw")))
    assert [n for n in ("order-items", "reviews.raw", "reviewsXraw", "order-items-dlq") if pattern.match(n)] == [
        "order-items", "reviews.raw"]


def test_config_file():
    pytest.importorskip("yaml")
    config = load_config(CONFIG_PATH)
    assert config.topics == ("payments", "orders", "order-items", "members-events", "clickstream", "reviews.raw")
    assert (config.trigger_seconds, config.starting_offsets) == (60, "earliest")


# ---------- 형식 검사기 연결과 실행 입구 ----------

def test_batch_with_the_format_checker(tmp_path):
    """실제 형식 검사기로 샘플 묶음을 쓰면 ② 31줄, ① 9줄, ④는 샘플 기대 오류 수다 (재처리 잡과 같은 검사기)."""
    pytest.importorskip("yaml")
    from pipelines.gold_b.format_check import FormatChecker

    checker = FormatChecker()
    summary = write_batch(sample_messages(), checker=checker, store=LocalStore(tmp_path), loaded_at=LOADED_AT)
    assert summary["rows"]["topic_messages"] == len(load_samples()) == 31
    assert summary["rows"]["payment_events"] == sum(s["expected"]["payment_events"] for s in load_samples()) == 9
    assert summary["rows"]["malformed_events"] == sum(len({e["field"] for e in s["expected"]["malformed"]})
                                                      for s in load_samples())
    assert {row["rule_version"] for row in all_rows(LocalStore(tmp_path), "malformed_events")} == {checker.rule_version}


class FakeQuery:
    def __init__(self):
        self.waited = False

    def awaitTermination(self):
        self.waited = True


def test_main_starts_the_stream_with_the_format_checker(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    from pipelines.gold_b.jobs import streaming_ingest

    seen: dict = {}
    query = FakeQuery()

    def fake_build_query(spark, **kwargs):
        seen.update(kwargs, spark=spark)
        return query

    monkeypatch.setattr(streaming_ingest, "build_query", fake_build_query)
    env = {"GOLD_B_LEDGER_ROOT": str(tmp_path), "GOLD_B_CHECKPOINT": str(tmp_path / "checkpoint"),
           "KAFKA_BOOTSTRAP": "localhost:9092"}
    logs: list[str] = []
    assert main([], env=env, session=lambda: "spark", log=logs.append) == 0
    assert query.waited and seen["spark"] == "spark"
    assert seen["checker"].rule_version == "0.2.0"
    assert isinstance(seen["store"], LocalStore)
    assert seen["config"].topics == load_config(CONFIG_PATH).topics
    assert logs[-1].startswith("적재 잡 시작")


def test_main_stops_when_settings_are_missing():
    pytest.importorskip("yaml")
    logs: list[str] = []
    assert main([], env={}, session=lambda: pytest.fail("Spark를 띄우면 안 된다"), log=logs.append) == 1
    assert logs[-1].startswith("적재 잡 준비 실패")
