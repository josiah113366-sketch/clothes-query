"""Bronze 지연 수집기 시험. Kafka·Connect는 가짜로 바꿔 계산·상태·파일 쓰기만 본다.

실제 Kafka로 한 번 돌려 보는 것은 작업 지시서(docs/tasks/gold-b-collector.md) 「완료 확인」에서 한다.
실행: python -m pytest -q pipelines/gold_b/tests (저장소 루트에서)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pipelines.gold_b.collector import bronze_lag_collector as lag
from test_ddl import parse_ddl

NOW = datetime(2026, 10, 21, 6, 30, 15, tzinfo=timezone.utc)
RUNNING = {"connector": {"state": "RUNNING"}, "tasks": [{"id": 0, "state": "RUNNING"}]}


class FakeKafka:
    """data: {토픽: {파티션: (남아 있는 가장 오래된 위치, 마지막 위치, 처리한 위치 또는 None)}}
    stamps: {(토픽, 파티션, 위치): 그 메시지의 Kafka 시각}"""

    def __init__(self, data, stamps=None, missing=(), error=None):
        self.data = data
        self.stamps = stamps or {}
        self.missing = set(missing)
        self.error = error
        self.groups: list[str] = []
        self.requested: dict = {}

    def partitions(self, topic):
        if self.error is not None:
            raise self.error
        if topic in self.missing:
            raise lag.TopicMissing(topic)
        return sorted(self.data[topic])

    def committed(self, group, topic, partitions):
        self.groups.append(group)
        return {p: self.data[topic][p][2] for p in partitions}

    def watermarks(self, topic, partition):
        low, end, _ = self.data[topic][partition]
        return low, end

    def timestamps(self, wanted):
        self.requested.update(wanted)
        return {key: self.stamps.get((*key, offset)) for key, offset in wanted.items()}

    def close(self):
        pass


class FakeConnect:
    def __init__(self, status=RUNNING, topics=(), error=None):
        self._status, self._topics, self._error = status, list(topics), error

    def status(self, connector):
        if self._error is not None:
            raise self._error
        return self._status

    def topics(self, connector):
        if self._error is not None:
            raise self._error
        return self._topics


def make_settings(tmp_path, **env):
    values = {"GOLD_B_LAG_OUTPUT": str(tmp_path / "bronze_lag_snapshots"), "GOLD_B_LAG_TOPICS": "payments"}
    values.update(env)
    return lag.Settings.from_env(values)


def measure(tmp_path, low, end, committed, stamp_age=None, connect=None):
    """payments 0번 파티션 하나를 잰 줄과 가짜 Kafka를 돌려준다. stamp_age는 읽을 메시지의 나이(초)."""
    stamps = {}
    if stamp_age is not None:
        stamps[("payments", 0, max(committed or 0, low))] = NOW - timedelta(seconds=stamp_age)
    kafka = FakeKafka({"payments": {0: (low, end, committed)}}, stamps)
    rows, skipped = lag.collect_once(make_settings(tmp_path), kafka, connect or FakeConnect(), NOW)
    assert skipped == []
    return rows[0], kafka


# ---------- 밀린 개수와 시간 ----------

def test_backlog_gives_count_and_age(tmp_path):
    row, kafka = measure(tmp_path, low=0, end=130, committed=100, stamp_age=170)
    assert (row["end_offset"], row["committed_offset"], row["lag_msgs"], row["lag_sec"]) == (130, 100, 30, 170.0)
    assert row["connector_state"] == "RUNNING"
    assert kafka.groups == ["connect-bronze-s3-sink"]      # 커넥터 이름으로 정한 S3 Sink 그룹
    assert kafka.requested == {("payments", 0): 100}       # 처리 안 된 가장 오래된 메시지 1건만 읽음


def test_nothing_behind_is_zero_without_reading_messages(tmp_path):
    row, kafka = measure(tmp_path, low=0, end=130, committed=130)
    assert (row["lag_msgs"], row["lag_sec"]) == (0, 0.0)
    assert kafka.requested == {}


def test_no_commit_yet_is_null(tmp_path):                   # 규칙 1
    row, kafka = measure(tmp_path, low=0, end=130, committed=None)
    assert (row["committed_offset"], row["lag_msgs"], row["lag_sec"]) == (None, None, None)
    assert kafka.requested == {}


def test_deleted_messages_use_oldest_kept_one(tmp_path):    # 규칙 2
    row, kafka = measure(tmp_path, low=80, end=100, committed=50, stamp_age=60)
    assert (row["lag_msgs"], row["lag_sec"]) == (50, 60.0)  # 개수는 그대로, 시간은 남은 80번 메시지 기준
    assert kafka.requested == {("payments", 0): 80}


def test_all_unprocessed_messages_deleted_age_is_null(tmp_path):
    row, kafka = measure(tmp_path, low=100, end=100, committed=50)
    assert (row["lag_msgs"], row["lag_sec"]) == (50, None)
    assert kafka.requested == {}


def test_unreadable_message_time_is_null(tmp_path):
    row, _ = measure(tmp_path, low=0, end=130, committed=100)
    assert (row["lag_msgs"], row["lag_sec"]) == (30, None)


def test_clock_skew_never_makes_negative_age(tmp_path):
    row, _ = measure(tmp_path, low=0, end=130, committed=100, stamp_age=-5)
    assert row["lag_sec"] == 0.0


# ---------- 커넥터 상태 (규칙 3) ----------

@pytest.mark.parametrize("status, expected", [
    (RUNNING, "RUNNING"),
    ({"connector": {"state": "RUNNING"}, "tasks": [{"id": 0, "state": "FAILED"}]}, "FAILED"),
    ({"connector": {"state": "PAUSED"}, "tasks": [{"id": 0, "state": "PAUSED"}]}, "PAUSED"),
    ({"connector": {"state": "FAILED"}, "tasks": []}, "FAILED"),
    ({}, "UNKNOWN"),
])
def test_connector_state_prefers_task_state(status, expected):
    assert lag.connector_state(status) == expected


def test_connect_unreachable_still_measures_listed_topics(tmp_path):
    row, _ = measure(tmp_path, 0, 130, 100, 170, connect=FakeConnect(error=lag.ConnectUnavailable("URLError")))
    assert (row["connector_state"], row["lag_msgs"], row["lag_sec"]) == ("UNREACHABLE", 30, 170.0)


def test_missing_connector_is_not_found(tmp_path):
    row, _ = measure(tmp_path, 0, 130, 130, connect=FakeConnect(error=lag.ConnectorNotFound()))
    assert row["connector_state"] == "NOT_FOUND"


# ---------- 대상 토픽 ----------

def test_topics_come_from_connector_config_when_not_listed(tmp_path):
    settings = make_settings(tmp_path, GOLD_B_LAG_TOPICS="")
    kafka = FakeKafka({"orders": {0: (0, 5, 5)}, "payments": {0: (0, 7, 7), 1: (0, 3, 3)}})
    rows, _ = lag.collect_once(settings, kafka, FakeConnect(topics=["orders", "payments"]), NOW)
    assert [(r["topic"], r["kafka_partition"]) for r in rows] == [("orders", 0), ("payments", 0), ("payments", 1)]


def test_no_listed_topics_and_connect_down_measures_nothing(tmp_path):
    settings = make_settings(tmp_path, GOLD_B_LAG_TOPICS="")
    with pytest.raises(lag.CollectorError):
        lag.collect_once(settings, FakeKafka({}), FakeConnect(error=lag.ConnectUnavailable("x")), NOW)


def test_topic_missing_in_kafka_is_skipped(tmp_path):
    kafka = FakeKafka({"payments": {0: (0, 1, 1)}}, missing={"reviews.raw"})
    rows, skipped = lag.collect_once(make_settings(tmp_path, GOLD_B_LAG_TOPICS="payments,reviews.raw"),
                                     kafka, FakeConnect(), NOW)
    assert [r["topic"] for r in rows] == ["payments"] and skipped == ["reviews.raw"]
    with pytest.raises(lag.CollectorError):              # 잴 토픽이 하나도 없으면 실패
        lag.collect_once(make_settings(tmp_path, GOLD_B_LAG_TOPICS="reviews.raw"), kafka, FakeConnect(), NOW)


# ---------- 저장과 실행 ----------

def test_run_once_writes_one_parquet_in_hour_folder_matching_ddl(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    settings = make_settings(tmp_path, GOLD_B_LAG_TOPICS="orders,payments")
    kafka = FakeKafka({"orders": {0: (0, 10, None)}, "payments": {0: (0, 130, 100), 1: (0, 7, 7)}},
                      {("payments", 0, 100): NOW - timedelta(seconds=170)})
    messages: list[str] = []
    assert lag.run_once(settings, kafka=kafka, connect=FakeConnect(), now=NOW, log=messages.append)

    files = list((tmp_path / "bronze_lag_snapshots" / "dt=2026-10-21" / "hour=06").iterdir())
    assert len(files) == 1 and files[0].suffix == ".parquet"   # 임시 파일이 남지 않음
    table = pq.ParquetFile(files[0]).read()
    ddl = parse_ddl("bronze_lag_snapshots")["columns"]
    assert table.column_names == [name for name, _ in ddl] == list(lag.COLUMNS)
    types = {"STRING": "string", "INT": "int32", "BIGINT": "int64", "DOUBLE": "double", "TIMESTAMP": "timestamp[us]"}
    assert [str(table.schema.field(name).type) for name, _ in ddl] == [types[kind] for _, kind in ddl]
    rows = table.to_pylist()
    assert [(r["topic"], r["kafka_partition"], r["lag_msgs"], r["lag_sec"]) for r in rows] == [
        ("orders", 0, None, None), ("payments", 0, 30, 170.0), ("payments", 1, 0, 0.0)]
    assert rows[0]["collected_at"] == NOW.replace(tzinfo=None)   # UTC 시각을 시간대 없이 저장
    assert "줄 3개" in messages[0]


def test_kafka_failure_writes_nothing_and_hides_details(tmp_path):   # 규칙 3
    messages: list[str] = []
    error = RuntimeError("Failed to connect to broker kafka-0.example:9093")
    assert not lag.run_once(make_settings(tmp_path), kafka=FakeKafka({}, error=error), connect=FakeConnect(),
                            now=NOW, log=messages.append)
    assert not (tmp_path / "bronze_lag_snapshots").exists()
    assert messages == ["측정 실패: RuntimeError"]                 # 오류 내용(주소)을 남기지 않음


# ---------- 설정 ----------

def test_settings_defaults_and_checks(tmp_path):
    settings = make_settings(tmp_path)
    assert settings.sink_group == "connect-bronze-s3-sink" and settings.topics == ("payments",)
    assert make_settings(tmp_path, GOLD_B_SINK_GROUP="custom-group").sink_group == "custom-group"
    assert "localhost" not in repr(settings)                    # 주소가 로그에 찍히지 않게
    for bad in ({"GOLD_B_LAG_OUTPUT": ""},
                {"KAFKA_SECURITY_PROTOCOL": "SASL_SSL"},
                {"KAFKA_SECURITY_PROTOCOL": "SSL", "KAFKA_SSL_CERT_FILE": "user.crt"},   # 키 없이 인증서만
                {"GOLD_B_CONNECT_URL": "file:///tmp/x"}):
        with pytest.raises(lag.ConfigError):
            make_settings(tmp_path, **bad)


def test_env_file_skips_comments_and_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# 주석\nGOLD_B_LAG_TOPICS=orders\nGOLD_B_SINK_CONNECTOR='member-s3-sink'\n\n잘못된 줄\n",
                        encoding="utf-8")
    assert lag.read_env_file(env_file) == {"GOLD_B_LAG_TOPICS": "orders", "GOLD_B_SINK_CONNECTOR": "member-s3-sink"}


def test_main_without_output_is_config_error(monkeypatch, capsys):
    monkeypatch.delenv("GOLD_B_LAG_OUTPUT", raising=False)
    assert lag.main(["--once"]) == 2
    assert "GOLD_B_LAG_OUTPUT" in capsys.readouterr().err
