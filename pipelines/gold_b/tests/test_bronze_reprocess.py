"""Bronze 재처리 시험: Kafka 보관 기간(7일)이 지난 시간 폴더는 Bronze v2 파일에서 메시지를 다시 만들어 재처리한다.

Bronze v2(connectors/bronze-s3-sink-v2.yaml)와 같은 모양의 파일을 샘플 메시지로 임시 폴더에 만든다:
<토픽>/year=YYYY/month=MM/day=dd/<토픽>+<파티션>+<시작offset>.json, 줄마다 메시지 값 + kafka_* 5칸.
Kafka Connect가 값을 다시 쓰면서 칸 순서가 바뀌는 것도 흉내 낸다 (값의 칸을 거꾸로 씀).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from pipelines.gold_b.jobs.reprocess import (DEFAULT_TOPICS, BronzeReader, Options, ReprocessError,  # noqa: E402
                                             check_request, from_bronze, main, run)
from pipelines.gold_b.ledger import Judgement, KafkaMessage, LocalStore, S3Store, message_rows, utc_naive  # noqa: E402
from test_reprocess import (H05, H06, H07, NOW, STREAMED_AT, TABLES, FakeKafka, SampleChecker,  # noqa: E402
                            comparable, events, folder_rows, in_hour, ledger_files, request, sample_messages,
                            streamed_rows, ticking, write_ledgers)

UTC = timezone.utc
LATER = NOW + timedelta(days=8)   # 2026-10-29 09:00 UTC: 2026-10-21 폴더는 Kafka 보관 기간(7일)이 지났다
SINK_TOPICS = ("payments", "orders", "order-items", "members-events", "clickstream")   # Bronze v2 토픽


# ---------- Bronze v2 파일 만들기 ----------

def sink_line(message: KafkaMessage) -> dict | None:
    """Sink가 쓰는 줄: Kafka 위치·시각 + 값(칸 순서는 거꾸로). 값이 JSON 객체가 아니면 Sink가 쓰지 않는다."""
    try:
        value = json.loads(message.value)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    at = message.timestamp.astimezone(UTC)
    return {"kafka_topic": message.topic, "kafka_partition": message.partition, "kafka_offset": message.offset,
            "kafka_timestamp": f"{at:%Y-%m-%dT%H:%M:%S}.{at.microsecond // 1000:03d}Z",
            "kafka_timestamp_type": "CreateTime", **dict(reversed(list(value.items())))}


def write_bronze(root: Path, messages: list[KafkaMessage]) -> set[tuple[str, int, int]]:
    """토픽·파티션·날짜(UTC)마다 파일 하나로 쓴다. Bronze에 들어간 메시지 위치를 돌려준다."""
    files: dict[tuple[str, int, object], list[dict]] = defaultdict(list)
    for m in sorted(messages, key=lambda m: m.position):
        line = sink_line(m)
        if m.topic in SINK_TOPICS and line is not None:
            files[(m.topic, m.partition, m.timestamp.astimezone(UTC).date())].append(line)
    for (topic, partition, day), lines in files.items():
        write_file(root, topic, day, f"{topic}+{partition}+{lines[0]['kafka_offset']:010d}.json", lines)
    return {(line["kafka_topic"], line["kafka_partition"], line["kafka_offset"])
            for lines in files.values() for line in lines}


def write_file(root: Path, topic: str, day, name: str, lines: list[dict]) -> None:
    folder = root / topic / f"year={day:%Y}" / f"month={day:%m}" / f"day={day:%d}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                               encoding="utf-8")


class NoKafka:
    """보관 기간이 지나 Kafka에서 읽을 수 없다. 읽으려 하면 시험이 실패한다."""

    def partitions(self, topic):
        raise AssertionError("보관 기간이 지난 폴더를 Kafka에서 읽으려 했다")

    offsets_for_time = read = partitions

    def close(self):
        pass


def position(table: str, row: dict) -> tuple[str, int, int]:
    return ("payments" if table == "payment_events" else row["topic"], row["kafka_partition"], row["kafka_offset"])


def broken(clean: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """06시 폴더에 놓친 결제·클릭, 두 번 쌓인 주문이 있는 원장 (test_reprocess와 같은 고장)."""
    rows = {table: list(items) for table, items in clean.items()}
    rows["payment_events"] = [r for r in rows["payment_events"] if (r["kafka_partition"], r["kafka_offset"]) != (0, 101)]
    rows["topic_messages"] = [r for r in rows["topic_messages"] if (r["topic"], r["kafka_offset"]) != ("clickstream", 18342)]
    rows["topic_messages"].append({**next(r for r in clean["topic_messages"] if r["topic"] == "orders"),
                                   "loaded_at": STREAMED_AT + timedelta(minutes=1)})
    return rows


def at_hour(messages: list[KafkaMessage], hour: datetime) -> set[tuple[str, int, int]]:
    return {m.position for m in messages if utc_naive(m.timestamp).replace(minute=0, second=0, microsecond=0) == hour}


# ---------- 시험 ----------

def test_old_hour_is_rebuilt_from_bronze(tmp_path):
    """보관 기간이 지난 06시 폴더를 Bronze만으로 교체한다: 놓친 메시지는 채우고 두 번 쌓인 메시지는 하나로.
    Bronze에 없는 메시지(JSON이 아닌 값, reviews.raw)의 줄은 옛 줄 그대로 남는다. Kafka는 읽지 않는다."""
    ledger, bronze_root = tmp_path / "gold_b", tmp_path / "bronze_v2"
    store, checker = LocalStore(ledger), SampleChecker()
    clean = streamed_rows(checker)
    write_ledgers(store, broken(clean))
    in_bronze = write_bronze(bronze_root, sample_messages()) & at_hour(sample_messages(), H06)
    before_05 = {path: data for path, data in ledger_files(ledger).items() if "hour=05" in path}

    result = run(request(), source=NoKafka(), store=store, checker=checker, now=ticking(LATER),
                 log=lambda _: None, bronze=BronzeReader(LocalStore(bronze_root)))

    assert result.replaced == [(H06, H07)]
    for table in TABLES:
        assert comparable(folder_rows(store, table, H06)) == comparable(in_hour(clean[table], table, H06)), table
    rows = [(table, row) for table in TABLES for row in folder_rows(store, table, H06)]
    assert {position(t, r) for t, r in rows if r["loaded_at"] >= utc_naive(LATER)} == in_bronze   # 다시 만든 줄
    assert {position(t, r) for t, r in rows if r["loaded_at"] < utc_naive(LATER)} == {   # Bronze에 없어 남은 옛 줄
        ("payments", 0, 104), ("reviews.raw", 0, 40), ("reviews.raw", 0, 41)}
    assert {path: data for path, data in ledger_files(ledger).items() if "hour=05" in path} == before_05

    started, replaced = events(store)
    assert (started["step"], started["source"]) == ("STARTED", "BRONZE")
    assert json.loads(started["detail"])["bronze_folders"] == ["2026-10-21T06:00"]
    assert (replaced["step"], replaced["window_start"], replaced["source"]) == ("LEDGER_REPLACED", H06, "BRONZE")
    detail = json.loads(replaced["detail"])
    assert (detail["messages"], detail["missing_topics"]) == (len(in_bronze), ["reviews.raw"])


# 위치는 06:09 메시지(3001) 뒤인데 시각은 05:58인 회원 메시지. Kafka 06시 범위에도, Bronze 05시에도 든다
LATE_STAMPED = KafkaMessage("members-events", 1, 3002, datetime(2026, 10, 21, 5, 58, tzinfo=UTC),
                            b'{"__op": "u", "__source_ts_ms": 1792562280000}')


class WithLateStamped(SampleChecker):
    def __call__(self, message):
        return Judgement() if message.position == LATE_STAMPED.position else super().__call__(message)


def test_mixed_window_reads_old_hours_from_bronze_and_recent_hours_from_kafka(tmp_path):
    """05~07시 요청을 보관 기간 경계에서 돌리면 05시는 Bronze, 06시는 Kafka에서 읽는다 (폴더마다 시각으로 고름).
    두 곳에서 다 읽힌 메시지(시각이 위치 순서와 다른 것)는 한 번만 쓴다."""
    ledger, bronze_root = tmp_path / "gold_b", tmp_path / "bronze_v2"
    store, checker = LocalStore(ledger), WithLateStamped()
    messages = [*sample_messages(), LATE_STAMPED]
    clean = streamed_rows(checker)
    clean["topic_messages"] += message_rows(LATE_STAMPED, Judgement(), "test", STREAMED_AT)["topic_messages"]
    rows = broken(clean)
    rows["topic_messages"] = [r for r in rows["topic_messages"] if r["topic"] != "members-events" or r["kafka_offset"] != 3000]
    write_ledgers(store, rows)
    write_bronze(bronze_root, messages)
    # 05시 메시지는 Kafka에서 지워졌다 (3002는 3001 뒤라 남음)
    kafka = FakeKafka([m for m in messages if m.timestamp >= H06.replace(tzinfo=UTC) or m == LATE_STAMPED])
    now = datetime(2026, 10, 28, 5, 30, tzinfo=UTC)   # 05시 폴더 - 10분(04:50)만 7일 전(10-21 05:30)보다 앞

    result = run(request(start=(5, 0), end=(7, 0)), source=kafka, store=store, checker=checker, now=ticking(now),
                 log=lambda _: None, bronze=BronzeReader(LocalStore(bronze_root)))

    assert result.replaced == [(H05, H06), (H06, H07)]
    for table in TABLES:
        for hour in (H05, H06):
            assert comparable(folder_rows(store, table, hour)) == comparable(in_hour(clean[table], table, hour)), table
    # 06시는 Kafka에서 읽어 Bronze에 없는 메시지(JSON이 아닌 값)도 다시 만들었다
    assert all(r["loaded_at"] > STREAMED_AT for r in folder_rows(store, "topic_messages", H06))
    started, *replaced = events(store)
    assert (started["source"], json.loads(started["detail"])["bronze_folders"]) == ("KAFKA", ["2026-10-21T05:00"])
    assert [(e["window_start"], e["source"], json.loads(e["detail"]).get("missing_topics")) for e in replaced] == [
        (H05, "BRONZE", ["reviews.raw"]), (H06, "KAFKA", None)]


class Relabeled:
    """지금 규칙표를 그대로 쓰고 버전만 바꾼다 (재처리로 다시 만든 줄을 rule_version으로 가린다)."""

    def __init__(self, version: str):
        from pipelines.format_rules import DEFAULT_RULES, FormatRules

        self._rules = FormatRules(DEFAULT_RULES, consumer="gold_b")
        self.version, self.datasets = version, self._rules.datasets

    def errors(self, dataset, row):
        return self._rules.errors(dataset, row)


def all_rows(root: Path) -> dict[str, list[dict]]:
    store = LocalStore(root)
    return {table: [row for path in sorted((root / table).rglob("*.parquet")) if not path.name.startswith(".")
                    for row in store.read(path.relative_to(root).as_posix(), table)] for table in TABLES}


def canonical(rows: dict[str, list[dict]], keep: set[tuple[str, int, int]]) -> dict[str, Counter]:
    """keep 위치의 줄 (loaded_at 빼고, raw_sample은 칸 순서와 상관없이)."""
    out = {}
    for table, items in rows.items():
        picked = []
        for row in items:
            if position(table, row) in keep:
                row = {k: v for k, v in row.items() if k != "loaded_at"}
                if row.get("raw_sample"):
                    row["raw_sample"] = json.loads(row["raw_sample"])
                picked.append(json.dumps(row, sort_keys=True, default=str, ensure_ascii=False))
        out[table] = Counter(picked)
    return out


def test_bronze_gives_the_same_rows_as_kafka(tmp_path):
    """실제 형식 검사기로 같은 메시지를 Kafka에서 다시 만든 줄과 Bronze에서 다시 만든 줄이 같다.
    Bronze 줄은 칸 순서가 달라도(Kafka Connect가 다시 씀) 검사 결과·결제 지문이 같고, raw_sample은 칸 순서만 다르다."""
    pytest.importorskip("yaml")
    from pipelines.gold_b.format_check import FormatChecker

    messages, current = sample_messages(), FormatChecker()
    in_bronze = write_bronze(tmp_path / "bronze_v2", messages)
    for name, now, sources in (("kafka", NOW, {"source": FakeKafka(messages)}),
                               ("bronze", LATER, {"source": NoKafka(),
                                                  "bronze": BronzeReader(LocalStore(tmp_path / "bronze_v2"))})):
        rows: dict[str, list[dict]] = {table: [] for table in TABLES}
        for m in messages:   # 평소 적재 잡이 지금 규칙으로 쌓은 원장
            for table, items in message_rows(m, current(m), current.rule_version, STREAMED_AT).items():
                rows[table].extend(items)
        write_ledgers(LocalStore(tmp_path / name), rows)
        run(request(start=(5, 0), end=(7, 0), rule_version="9.9.9-test"), store=LocalStore(tmp_path / name),
            checker=FormatChecker(Relabeled("9.9.9-test")), now=ticking(now), log=lambda _: None, **sources)

    kafka, bronze = all_rows(tmp_path / "kafka"), all_rows(tmp_path / "bronze")
    assert canonical(bronze, in_bronze) == canonical(kafka, in_bronze)
    # 결제 줄과 오류 줄 모두 Bronze에서 새 규칙 버전으로 다시 만들었다 (비교가 빈 것끼리가 아님)
    assert any(r["rule_version"] == "9.9.9-test" for r in bronze["payment_events"])
    assert any(r["rule_version"] == "9.9.9-test" and r["raw_sample"] for r in bronze["malformed_events"])


def test_a_message_written_twice_to_bronze_counts_once(tmp_path):
    """Sink가 다시 켜져 같은 메시지가 두 파일에 들어가도 위치로 하나만 쓴다."""
    ledger, bronze_root = tmp_path / "gold_b", tmp_path / "bronze_v2"
    store, checker = LocalStore(ledger), SampleChecker()
    write_ledgers(store, streamed_rows(checker))
    in_bronze = write_bronze(bronze_root, sample_messages()) & at_hour(sample_messages(), H06)
    again = [sink_line(m) for m in sample_messages() if m.topic == "payments" and m.partition == 0 and m.offset >= 101
             and sink_line(m) is not None]
    write_file(bronze_root, "payments", H06.date(), "payments+0+0000000101.json", again)   # 101부터 다시 씀

    found, _ = BronzeReader(LocalStore(bronze_root)).read(DEFAULT_TOPICS, [H06])
    assert sorted(m.position for m in found) == sorted(in_bronze)   # 읽을 때 이미 위치마다 하나

    run(request(), source=NoKafka(), store=store, checker=checker, now=ticking(LATER), log=lambda _: None,
        bronze=BronzeReader(LocalStore(bronze_root)))

    counts = Counter(position("topic_messages", r) for r in folder_rows(store, "topic_messages", H06))
    assert set(counts.values()) == {1}
    assert Counter(position("payment_events", r) for r in folder_rows(store, "payment_events", H06)).most_common(1)[0][1] == 1
    assert json.loads(events(store)[-1]["detail"])["messages"] == len(in_bronze)


@pytest.mark.parametrize("case", ["no_files", "old_format"])
def test_missing_or_old_bronze_fails_without_retry(tmp_path, case):
    """그 날의 Bronze 파일이 하나도 없거나 줄에 Kafka 위치·시각이 없으면(옛 bronze/ 형식) 원장을 건드리지 않고 멈춘다."""
    ledger, bronze_root = tmp_path / "gold_b", tmp_path / "bronze_v2"
    store, checker = LocalStore(ledger), SampleChecker()
    write_ledgers(store, streamed_rows(checker))
    before = ledger_files(ledger)
    if case == "old_format":
        values = [json.loads(m.value) for m in sample_messages() if m.topic == "orders"]
        write_file(bronze_root, "orders", H06.date(), "orders+0+0000000500.json", values)

    with pytest.raises(ReprocessError) as raised:
        run(request(), source=NoKafka(), store=store, checker=checker, now=ticking(LATER), log=lambda _: None,
            bronze=BronzeReader(LocalStore(bronze_root)))

    assert raised.value.retryable is False
    assert ("원본이 없다" if case == "no_files" else "bronze_v2") in str(raised.value)
    assert [(e["step"], e["source"]) for e in events(store)] == [("STARTED", "BRONZE"), ("FAILED", "BRONZE")]
    assert json.loads(events(store)[-1]["detail"])["retryable"] is False
    assert ledger_files(ledger) == before


def test_old_requests_need_the_bronze_location():
    """Bronze 위치가 없으면 보관 기간이 지난 요청은 시작 전에 거부한다. 경계는 폴더 시작 - 10분 < 지금 - 7일."""
    old = datetime(2026, 10, 28, 6, 0)
    with pytest.raises(ReprocessError, match="Bronze 위치"):
        check_request(request(), SampleChecker(), Options(), old)
    assert check_request(request(), SampleChecker(), Options(), old, bronze=True) == [H06]
    assert from_bronze([H05, H06], Options(), datetime(2026, 10, 28, 5, 50)) == [H05]   # 06:00 - 10분 = 7일 전: Kafka
    assert from_bronze([H05, H06], Options(), datetime(2026, 10, 28, 5, 51)) == [H05, H06]
    assert from_bronze([H05, H06], Options(), datetime(2026, 10, 28, 4, 50)) == []


def test_main_reads_the_bronze_location_from_env(tmp_path, monkeypatch):
    """GOLD_B_BRONZE_ROOT가 있으면 보관 기간이 지난 승인 요청을 Bronze로 돌린다. 없으면 시작 전에 거부한다."""
    pytest.importorskip("yaml")
    from pipelines.gold_b.format_check import FormatChecker
    from pipelines.gold_b.jobs import reprocess

    approved = {"request_id": "rq-old", "step": "APPROVED", "at": utc_naive(LATER) - timedelta(minutes=10),
                "actor": "test", "reason": None, "window_start": datetime(2026, 10, 21, 6, 10),
                "window_end": datetime(2026, 10, 21, 6, 30), "rule_version": FormatChecker().rule_version,
                "source": "KAFKA", "attempt": 1, "parent_request_id": None, "detail": None}
    write_bronze(tmp_path / "bronze_v2", sample_messages())
    monkeypatch.setattr(reprocess, "KafkaReader", lambda config: NoKafka())
    results = {}
    for name, bronze_env in (("with", {"GOLD_B_BRONZE_ROOT": str(tmp_path / "bronze_v2")}), ("without", {})):
        ledger = LocalStore(tmp_path / name)
        ledger.write("reprocess_events/part-approved.parquet", "reprocess_events", [approved])
        env = {"GOLD_B_LEDGER_ROOT": str(tmp_path / name), "KAFKA_BOOTSTRAP": "localhost:9092", **bronze_env}
        code = main([], env=env, now=ticking(LATER), log=lambda _: None)
        results[name] = (code, [(e["step"], e["source"]) for e in events(ledger)])

    assert results["with"] == (0, [("APPROVED", "KAFKA"), ("STARTED", "BRONZE"), ("LEDGER_REPLACED", "BRONZE")])
    assert results["without"] == (1, [("APPROVED", "KAFKA"), ("FAILED", None)])
    assert folder_rows(LocalStore(tmp_path / "with"), "payment_events", H06)   # 실제 형식 검사기로 결제 줄을 만들었다


class FakeS3:
    """boto3 S3 클라이언트 흉내 (목록·읽기만)."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def test_bronze_is_read_from_the_sink_paths_on_s3(tmp_path):
    """S3에서는 Sink 경로(bronze_v2/<토픽>/year=/month=/day=/)를 읽고, 되돌린 값·위치·시각이 원래 메시지와 같다."""
    root = tmp_path / "bronze_v2"
    write_bronze(root, sample_messages())
    objects = {"bronze_v2/" + p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.json")}
    assert "bronze_v2/payments/year=2026/month=10/day=21/payments+0+0000000100.json" in objects

    found, missing = BronzeReader(S3Store("s3://example-bucket/bronze_v2", client=FakeS3(objects))).read(
        DEFAULT_TOPICS, [H06])

    originals = {m.position: m for m in sample_messages()}
    assert missing == ["reviews.raw"]
    assert [m.position for m in found] == sorted(at_hour(sample_messages(), H06) & {
        p for p in originals if p[0] in SINK_TOPICS and sink_line(originals[p]) is not None})
    for m in found:
        assert (m.timestamp, json.loads(m.value)) == (originals[m.position].timestamp,
                                                      json.loads(originals[m.position].value))
