"""재처리 잡 시험. 가짜 Kafka와 샘플 메시지(samples/)로 교체 결과와 reprocess_events 기록을 확인한다.

실제 Kafka·S3에는 붙지 않는다. 원장은 임시 폴더(LocalStore)에 쓴다.
형식 검사는 아직 없어서 샘플의 기대 결과대로 판정하는 가짜(SampleChecker)를 쓴다.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json

import pytest

pytest.importorskip("pyarrow")

import pyarrow.parquet as pq  # noqa: E402

from pipelines.gold_b.jobs.reprocess import (Options, ReprocessError, Request, TopicMissing,  # noqa: E402
                                             check_request, hour_folders, main, next_request, read_events, run)
from pipelines.gold_b.ledger import (EVENT_TIME, TABLE_COLUMNS, Judgement, KafkaMessage,  # noqa: E402
                                     LocalStore, hour_folder, hour_of, message_rows, to_arrow)
from test_ddl import _utc, load_samples, parse_ddl, stand_in_fingerprint  # noqa: E402

UTC = timezone.utc
H05, H06, H07 = (datetime(2026, 10, 21, h) for h in (5, 6, 7))
STREAMED_AT = datetime(2026, 10, 21, 6, 30)     # 평소 적재 잡이 쌓은 시각 (가정)
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
TABLES = ("payment_events", "topic_messages", "malformed_events")
LATE_PAYMENT = {   # Kafka에서 다시 읽지 못하는 결제 줄 (예: 여유 시간보다 늦게 들어와 평소 적재 잡만 쌓은 것)
    "payment_id": "00000000-4000-8000-0000-0000000000f9", "order_id": "00000000-4000-8000-0000-0000000000e9",
    "attempt_no": 1, "pg": "PG_A", "status": "SUCCESS", "failure_code": None,
    "completed_at": datetime(2026, 10, 21, 6, 59), "payment_content_hash": "late", "fingerprint_version": "test",
    "kafka_partition": 0, "kafka_offset": 999, "loaded_at": STREAMED_AT,
    "cdc_op": "c", "source_ts_ms": 1792565940000, "rule_version": "test"}


# ---------- 가짜 Kafka, 가짜 형식 검사 ----------

def sample_messages() -> list[KafkaMessage]:
    messages = []
    for s in load_samples():
        k = s["kafka"]
        raw = s["value_raw"] if "value_raw" in s else json.dumps(s["value"], ensure_ascii=False)
        messages.append(KafkaMessage(k["topic"], k["partition"], k["offset"], _utc(k["timestamp"]),
                                     raw.encode("utf-8")))
    return messages


class FakeKafka:
    def __init__(self, messages: list[KafkaMessage]):
        self.messages = sorted(messages, key=lambda m: m.position)
        self.reads = 0

    def partitions(self, topic):
        found = sorted({m.partition for m in self.messages if m.topic == topic})
        if not found:
            raise TopicMissing(topic)
        return found

    def offsets_for_time(self, topic, partitions, at):
        at = at.replace(tzinfo=UTC)
        offsets = {}
        for p in partitions:
            mine = [m for m in self.messages if (m.topic, m.partition) == (topic, p)]
            after = [m.offset for m in mine if m.timestamp >= at]
            offsets[p] = min(after) if after else max(m.offset for m in mine) + 1
        return offsets

    def read(self, ranges):
        self.reads += 1
        return [m for m in self.messages
                if (m.topic, m.partition) in ranges
                and ranges[(m.topic, m.partition)][0] <= m.offset < ranges[(m.topic, m.partition)][1]]

    def close(self):
        pass


# 오류 줄의 record_key로 쓰는 메시지 키 (format_check.RECORD_KEYS와 같음, 토픽 이름 기준)
RECORD_KEYS = {"payments": "payment_id", "orders": "order_id", "order-items": "order_item_id",
               "clickstream": "event_id"}


class SampleChecker:
    """샘플의 기대 결과대로 판정한다. accept_pg_c=True면 PG_C를 허용하는 새 규칙처럼 판정한다."""

    def __init__(self, rule_version: str = "test", accept_pg_c: bool = False):
        self.rule_version = rule_version
        self._accept_pg_c = accept_pg_c
        self._samples = {(s["kafka"]["topic"], s["kafka"]["partition"], s["kafka"]["offset"]): s
                         for s in load_samples()}

    def __call__(self, message: KafkaMessage) -> Judgement:
        s = self._samples[message.position]
        if s["expected"]["payment_events"] or (self._accept_pg_c and s["name"] == "pg_c"):
            v = s["value"]
            return Judgement(payment={
                "payment_id": v["payment_id"], "order_id": v["order_id"], "attempt_no": v["attempt_no"],
                "pg": v["pg"], "status": v["status"], "failure_code": v["failure_code"],
                "completed_at": _utc(v["completed_at"]), "payment_content_hash": stand_in_fingerprint(v),
                "fingerprint_version": "test", "cdc_op": v["__op"], "source_ts_ms": v["__source_ts_ms"]})
        value = s.get("value") if isinstance(s.get("value"), dict) else {}
        key_field = RECORD_KEYS.get(s["kafka"]["topic"])
        return Judgement(errors=[{"field": e["field"], "reason": e["reason"],
                                  "raw_sample": "<masked>" if i == 0 else None,
                                  "record_key": value.get(key_field) if key_field else None,
                                  "source_ts_ms": value.get("__source_ts_ms")}
                                 for i, e in enumerate(s["expected"]["malformed"])])


# ---------- 원장 준비와 읽기 ----------

def streamed_rows(checker: SampleChecker, loaded_at: datetime = STREAMED_AT) -> dict[str, list[dict]]:
    """평소 적재 잡이 모든 샘플 메시지를 쌓았을 때의 원장 줄."""
    rows = {table: [] for table in TABLES}
    for message in sample_messages():
        for table, items in message_rows(message, checker(message), checker.rule_version, loaded_at).items():
            rows[table].extend(items)
    return rows


def write_ledgers(store: LocalStore, rows: dict[str, list[dict]], name: str = "part-stream.parquet") -> None:
    for table, items in rows.items():
        by_hour: dict[datetime, list[dict]] = {}
        for row in items:
            by_hour.setdefault(hour_of(row[EVENT_TIME[table]]), []).append(row)
        for hour, part in by_hour.items():
            store.write(f"{hour_folder(table, hour)}/{name}", table, part)


def in_hour(rows: list[dict], table: str, hour: datetime) -> list[dict]:
    return [row for row in rows if hour_of(row[EVENT_TIME[table]]) == hour]


def folder_rows(store: LocalStore, table: str, hour: datetime) -> list[dict]:
    return [row for path in store.files(hour_folder(table, hour)) for row in store.read(path, table)]


def comparable(rows: list[dict]) -> Counter:
    """loaded_at을 뺀 줄 묶음 (순서 무시, 같은 줄이 두 번이면 2로 셈)."""
    return Counter(tuple(sorted((k, v) for k, v in row.items() if k != "loaded_at")) for row in rows)


def events(store: LocalStore) -> list[dict]:
    rows = [row for path in store.files("reprocess_events") for row in store.read(path, "reprocess_events")]
    return sorted(rows, key=lambda row: row["at"])


def ledger_files(root) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.parquet")
            if "reprocess_events" not in p.parts}


def ticking(start: datetime = NOW):
    """부를 때마다 1초씩 가는 시계 (기록 순서를 at으로 가릴 수 있게)."""
    current = [start]

    def now():
        current[0] += timedelta(seconds=1)
        return current[0]
    return now


def request(rid: str = "rq-1", start=(6, 10), end=(6, 30), rule_version: str = "test", attempt: int = 1):
    return Request(rid, datetime(2026, 10, 21, *start, tzinfo=UTC), datetime(2026, 10, 21, *end, tzinfo=UTC),
                   rule_version, attempt=attempt)


# ---------- 시험 ----------

@pytest.mark.parametrize("table", sorted(TABLE_COLUMNS))
def test_ledger_schemas_match_ddl(table):
    assert list(TABLE_COLUMNS[table]) == parse_ddl(table)["columns"]


def test_one_error_row_per_field():
    message = KafkaMessage("payments", 0, 7, datetime(2026, 10, 21, 6, 1, tzinfo=UTC), b"{}")
    judgement = Judgement(errors=[{"field": "pg", "reason": "INVALID_VALUE"},
                                  {"field": "pg", "reason": "TYPE_MISMATCH"},
                                  {"field": "status", "reason": "MISSING_FIELD"}])
    rows = message_rows(message, judgement, "test", STREAMED_AT)["malformed_events"]
    assert [(r["field"], r["reason"]) for r in rows] == [("pg", "INVALID_VALUE"), ("status", "MISSING_FIELD")]


def test_hour_folders():
    at = lambda h, m: datetime(2026, 10, 21, h, m, tzinfo=UTC)  # noqa: E731
    assert hour_folders(at(14, 40), at(16, 20)) == [datetime(2026, 10, 21, h) for h in (14, 15, 16)]
    assert hour_folders(at(15, 0), at(16, 0)) == [datetime(2026, 10, 21, 15)]
    kst = timezone(timedelta(hours=9))   # 한국 시각으로 들어와도 UTC 폴더로 바꾼다
    assert hour_folders(datetime(2026, 10, 21, 15, 10, tzinfo=kst), datetime(2026, 10, 21, 15, 30, tzinfo=kst)) == [H06]
    with pytest.raises(ReprocessError):
        hour_folders(at(16, 0), at(16, 0))


def test_reprocess_rebuilds_the_hour_folder(tmp_path):
    """놓친 메시지와 두 번 쌓인 메시지가 있는 06시 폴더를 교체하면 Kafka 그대로의 원장이 된다. 05시 폴더는 그대로다."""
    store, checker = LocalStore(tmp_path), SampleChecker()
    clean = streamed_rows(checker)
    broken = {table: list(rows) for table, rows in clean.items()}
    broken["payment_events"] = [r for r in broken["payment_events"] if (r["kafka_partition"], r["kafka_offset"]) != (0, 101)]
    broken["topic_messages"] = [r for r in broken["topic_messages"] if (r["topic"], r["kafka_offset"]) != ("clickstream", 18342)]
    broken["topic_messages"].append({**next(r for r in clean["topic_messages"] if r["topic"] == "orders"),
                                     "loaded_at": STREAMED_AT + timedelta(minutes=1)})
    write_ledgers(store, broken)
    before_05 = {path: data for path, data in ledger_files(tmp_path).items() if "hour=05" in path}

    result = run(request(), source=FakeKafka(sample_messages()), store=store, checker=checker,
                 now=ticking(), log=lambda _: None)

    assert result.replaced == [(H06, H07)]
    for table in TABLES:
        assert comparable(folder_rows(store, table, H06)) == comparable(in_hour(clean[table], table, H06)), table
        assert len(store.files(hour_folder(table, H06))) == 1
    assert {path: data for path, data in ledger_files(tmp_path).items() if "hour=05" in path} == before_05

    started, replaced = events(store)
    assert (started["step"], started["window_start"], started["window_end"]) == (
        "STARTED", datetime(2026, 10, 21, 6, 10), datetime(2026, 10, 21, 6, 30))
    assert (replaced["step"], replaced["window_start"], replaced["window_end"], replaced["source"]) == (
        "LEDGER_REPLACED", H06, H07, "KAFKA")
    assert (replaced["actor"], replaced["rule_version"], replaced["attempt"]) == ("reprocess_job", "test", 1)
    assert json.loads(replaced["detail"])["written"] == {t: len(in_hour(clean[t], t, H06)) for t in TABLES}
    # 판정 잡은 교체 때 쌓인 줄을 loaded_at <= LEDGER_REPLACED.at 으로 가린다
    assert all(r["loaded_at"] <= replaced["at"] for r in folder_rows(store, "payment_events", H06))


def test_same_input_twice_gives_the_same_ledgers(tmp_path):
    store, checker, kafka = LocalStore(tmp_path), SampleChecker(), FakeKafka(sample_messages())
    write_ledgers(store, streamed_rows(checker))
    clock = ticking()

    run(request("rq-1"), source=kafka, store=store, checker=checker, now=clock, log=lambda _: None)
    first = {table: comparable(folder_rows(store, table, H06)) for table in TABLES}
    run(request("rq-2"), source=kafka, store=store, checker=checker, now=clock, log=lambda _: None)

    assert {table: comparable(folder_rows(store, table, H06)) for table in TABLES} == first


def test_rows_not_reread_and_other_rule_versions_are_kept(tmp_path):
    """규칙 v2(PG_C 허용)로 재처리: 다시 읽지 못한 결제 줄과 옛 규칙의 오류 줄은 남고, PG_C 결제는 새로 들어온다."""
    store, old = LocalStore(tmp_path), SampleChecker()
    streamed = streamed_rows(old)
    streamed["payment_events"].append(LATE_PAYMENT)
    write_ledgers(store, streamed)

    run(request(rule_version="v2"), source=FakeKafka(sample_messages()), store=store,
        checker=SampleChecker("v2", accept_pg_c=True), now=ticking(), log=lambda _: None)

    payments = folder_rows(store, "payment_events", H06)
    assert [p for p in payments if p["kafka_offset"] == 999] == [LATE_PAYMENT]
    assert any(p["pg"] == "PG_C" for p in payments)
    malformed = folder_rows(store, "malformed_events", H06)
    assert comparable([r for r in malformed if r["rule_version"] == "test"]) == comparable(
        in_hour(streamed["malformed_events"], "malformed_events", H06))
    pg_c = ("payments", 1, 204)   # PG_C 샘플 위치: 옛 규칙 오류 줄만 있고 새 규칙 오류 줄은 없다
    assert {r["rule_version"] for r in malformed
            if (r["topic"], r["kafka_partition"], r["kafka_offset"]) == pg_c} == {"test"}
    assert len([r for r in malformed if r["rule_version"] == "v2"]) == len(
        [r for r in malformed if r["rule_version"] == "test"]) - 1


@pytest.mark.parametrize("case", ["unfinished", "out_of_retention", "rule_version", "empty_window"])
def test_refuses_before_start(tmp_path, case):
    store, checker, kafka = LocalStore(tmp_path), SampleChecker(), FakeKafka(sample_messages())
    write_ledgers(store, streamed_rows(checker))
    before = ledger_files(tmp_path)
    req, now = request(), NOW
    if case == "unfinished":            # 06시 폴더 끝 07:00 + 10분이 아직 안 됨
        now = datetime(2026, 10, 21, 7, 5, tzinfo=UTC)
    elif case == "out_of_retention":    # 05:50부터 읽어야 하는데 7일이 지남
        now = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    elif case == "rule_version":
        req = request(rule_version="v9")
    else:
        req = request(start=(6, 30), end=(6, 30))

    with pytest.raises(ReprocessError) as raised:
        run(req, source=kafka, store=store, checker=checker, now=ticking(now), log=lambda _: None)

    assert raised.value.retryable is False
    assert [e["step"] for e in events(store)] == ["FAILED"]
    assert json.loads(events(store)[0]["detail"])["retryable"] is False
    assert kafka.reads == 0
    assert ledger_files(tmp_path) == before


def test_kafka_retention_is_seven_days():
    """Kafka 보관 기간은 7일이다 (#86). 3~7일 전 구간도 Kafka에서 다시 읽고, 7일이 넘으면 거부한다."""
    assert Options().retention == timedelta(days=7)
    assert check_request(request(), SampleChecker(), Options(), datetime(2026, 10, 27, 6, 0)) == [
        datetime(2026, 10, 21, 6)]   # 6일 전 (예전 72시간 기준이면 거부)
    with pytest.raises(ReprocessError):
        check_request(request(), SampleChecker(), Options(), datetime(2026, 10, 28, 6, 0))


class CrashOnceStore(LocalStore):
    """06시 폴더에서 새 파일을 쓴 뒤 옛 파일을 지우다가 한 번 멈춘다."""

    def __init__(self, root):
        super().__init__(root)
        self.crashed = False

    def delete(self, paths):
        if not self.crashed and any("hour=06" in path for path in paths):
            self.crashed = True
            raise OSError("멈춤 (시험)")
        super().delete(paths)


def test_failure_midway_then_retry(tmp_path):
    """05·06시를 승인. 06시 교체 중에 멈추면 05시만 LEDGER_REPLACED, 06시는 FAILED. 다시 돌리면 같은 줄 없이 정리된다."""
    checker, kafka = SampleChecker(), FakeKafka(sample_messages())
    clean = streamed_rows(checker)
    seeded = {table: list(rows) for table, rows in clean.items()}
    seeded["payment_events"].append(LATE_PAYMENT)
    store = CrashOnceStore(tmp_path)
    write_ledgers(store, seeded)
    clock = ticking()

    with pytest.raises(OSError):
        run(request(start=(5, 30), end=(6, 30)), source=kafka, store=store, checker=checker, now=clock,
            log=lambda _: None)
    steps = [(e["step"], e["window_start"], e["window_end"]) for e in events(store)]
    assert steps == [("STARTED", datetime(2026, 10, 21, 5, 30), datetime(2026, 10, 21, 6, 30)),
                     ("LEDGER_REPLACED", H05, H06), ("FAILED", H06, H07)]
    failed = json.loads(events(store)[-1]["detail"])
    assert (failed["error"], failed["retryable"], failed["replaced_folders"]) == ("OSError", True, 1)
    assert len(store.files(hour_folder("payment_events", H06))) == 2   # 새 파일은 썼고 옛 파일은 못 지움

    run(request(start=(5, 30), end=(6, 30), attempt=2), source=kafka, store=store, checker=checker, now=clock,
        log=lambda _: None)

    assert [e["step"] for e in events(store)][3:] == ["STARTED", "LEDGER_REPLACED", "LEDGER_REPLACED"]
    expected = {table: in_hour(seeded[table], table, H06) for table in TABLES}
    for table in TABLES:
        assert comparable(folder_rows(store, table, H06)) == comparable(expected[table]), table
        assert comparable(folder_rows(store, table, H05)) == comparable(in_hour(clean[table], table, H05)), table


# ---------- poller (다음에 돌릴 요청 고르기) ----------

T = datetime(2026, 10, 21, 8, 0)    # 시험의 기준 시각 (UTC)
FOLDER_06 = ((6, 0), (7, 0))
FOLDER_05 = ((5, 0), (6, 0))


def ev(rid, step, minutes, *, source="KAFKA", window=((6, 10), (6, 30)), detail=None, attempt=1, parent=None):
    """reprocess_events 한 줄. minutes는 T로부터 몇 분 뒤에 기록했는지."""
    (sh, sm), (eh, em) = window
    return {"request_id": rid, "step": step, "at": T + timedelta(minutes=minutes), "actor": "test", "reason": None,
            "window_start": datetime(2026, 10, 21, sh, sm), "window_end": datetime(2026, 10, 21, eh, em),
            "rule_version": "0.2.0", "source": source, "attempt": attempt, "parent_request_id": parent,
            "detail": None if detail is None else json.dumps(detail)}


def test_poller_takes_gold_b_approvals_oldest_first():
    rows = [ev("rq-silver", "REQUESTED", 0, source="SILVER"), ev("rq-silver", "APPROVED", 1, source="SILVER"),
            ev("rq-late", "REQUESTED", 2), ev("rq-late", "APPROVED", 4),
            ev("rq-early", "REQUESTED", 2), ev("rq-early", "APPROVED", 3, attempt=2, parent="rq-old"),
            ev("rq-waiting", "REQUESTED", 1)]
    found = next_request(rows, T + timedelta(minutes=10))
    assert found.run_number == 1
    assert found.request == Request("rq-early", datetime(2026, 10, 21, 6, 10), datetime(2026, 10, 21, 6, 30),
                                    "0.2.0", attempt=2, parent_request_id="rq-old")


RETRYABLE, FINAL = {"error": "KafkaException", "retryable": True}, {"error": "보관 기간 밖", "retryable": False}


@pytest.mark.parametrize("rows,minutes,expected", [
    ([ev("rq-1", "APPROVED", 0)], 10, ("rq-1", 1)),                                            # 처음 돌림
    ([ev("rq-1", "APPROVED", 0)], 61, None),                                                   # 승인 뒤 60분 넘음: 승인 만료
    ([ev("rq-1", "REQUESTED", 0), ev("rq-1", "REJECTED", 1)], 10, None),                       # 거절
    ([ev("rq-1", "APPROVED", 0), ev("rq-1", "STARTED", 1),
      ev("rq-1", "LEDGER_REPLACED", 2, window=FOLDER_06)], 10, None),                          # 끝남
    ([ev("rq-1", "APPROVED", 0), ev("rq-1", "FAILED", 1, detail=FINAL)], 10, None),            # 다시 돌려도 소용없는 실패
    ([ev("rq-1", "APPROVED", 0), ev("rq-1", "STARTED", 1),
      ev("rq-1", "FAILED", 2, detail=RETRYABLE)], 10, ("rq-1", 2)),                            # 일시 실패: 다시 돌림
    ([ev("rq-1", "APPROVED", 0), ev("rq-1", "STARTED", 1),
      ev("rq-1", "FAILED", 2, detail=RETRYABLE)], 120, ("rq-1", 2)),                           # 시작한 뒤에는 승인 만료 없음
    ([ev("rq-1", "APPROVED", 0, window=((5, 10), (6, 30))), ev("rq-1", "STARTED", 1, window=((5, 10), (6, 30))),
      ev("rq-1", "LEDGER_REPLACED", 2, window=FOLDER_05)], 10, ("rq-1", 2)),                   # 06시 폴더 전에 멈춤
    ([ev("rq-1", "APPROVED", 0)] + [ev("rq-1", step, n, detail=RETRYABLE if step == "FAILED" else None)
                                    for n, step in enumerate(["STARTED", "FAILED"] * 3, 1)], 10, None),   # 세 번 다 돌림
])
def test_poller_rules(rows, minutes, expected):
    found = next_request(rows, T + timedelta(minutes=minutes))
    assert (None if found is None else (found.request.request_id, found.run_number)) == expected


def test_read_events_also_reads_files_athena_wrote(tmp_path):
    """승인 화면·판정 잡은 Athena INSERT로 쓴다. 그 파일은 이름에 확장자가 없을 수 있다."""
    store = LocalStore(tmp_path)
    store.write("reprocess_events/part-20261021T080100-started-abcd.parquet", "reprocess_events",
                [ev("rq-1", "STARTED", 1)])
    folder = tmp_path / "reprocess_events"
    pq.write_table(to_arrow("reprocess_events", [ev("rq-1", "APPROVED", 0)]), folder / "20261021_080000_00001_abcde")
    (folder / ".part-x.parquet.tmp").write_bytes(b"temp")
    (folder / "_SUCCESS").write_bytes(b"")
    assert sorted(row["step"] for row in read_events(store)) == ["APPROVED", "STARTED"]
    # 원장을 읽을 때 쓰는 기본 목록은 그대로 우리 잡이 쓴 .parquet만
    assert store.files("reprocess_events") == ["reprocess_events/part-20261021T080100-started-abcd.parquet"]


def test_run_number_is_recorded_and_finished_request_is_not_picked_again(tmp_path):
    store, checker = LocalStore(tmp_path), SampleChecker()
    write_ledgers(store, streamed_rows(checker))
    run(request(), source=FakeKafka(sample_messages()), store=store, checker=checker, now=ticking(),
        log=lambda _: None, run_number=2)
    assert json.loads(events(store)[0]["detail"])["run"] == 2
    approved = {**ev("rq-1", "APPROVED", 0), "rule_version": "test"}
    assert next_request([approved, *read_events(store)], NOW) is None


# ---------- 실행 입구 (python -m pipelines.gold_b.jobs.reprocess) ----------

def write_approval(root, rid: str = "rq-1", minutes: int = 30) -> None:
    """승인 화면이 Athena INSERT로 쓴 것처럼 확장자 없는 파일에 APPROVED 줄을 둔다 (규칙 버전은 규칙표와 같은 0.2.0)."""
    folder = root / "reprocess_events"
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(to_arrow("reprocess_events", [ev(rid, "APPROVED", minutes)]), folder / f"approval_{rid}")


def test_main_needs_ledger_root_and_reports_nothing_to_do(tmp_path):
    logs: list[str] = []
    assert main([], env={}, log=logs.append) == 1
    assert main([], env={"GOLD_B_LEDGER_ROOT": str(tmp_path)}, now=lambda: NOW, log=logs.append) == 0
    assert logs[-1] == "돌릴 재처리 요청이 없다"


def test_main_dry_run_only_names_the_request(tmp_path):
    write_approval(tmp_path)
    logs: list[str] = []
    assert main(["--dry-run"], env={"GOLD_B_LEDGER_ROOT": str(tmp_path)}, now=lambda: NOW, log=logs.append) == 0
    assert "rq-1" in logs[-1] and "1번째 실행" in logs[-1]
    assert [row["step"] for row in read_events(LocalStore(tmp_path))] == ["APPROVED"]


def test_main_runs_the_approved_request_with_the_format_checker(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    from pipelines.gold_b.jobs import reprocess

    write_approval(tmp_path)
    monkeypatch.setattr(reprocess, "KafkaReader", lambda config: FakeKafka(sample_messages()))
    env = {"GOLD_B_LEDGER_ROOT": str(tmp_path), "KAFKA_BOOTSTRAP": "localhost:9092"}
    assert main([], env=env, now=ticking(), log=lambda _: None) == 0
    steps = [row["step"] for row in sorted(read_events(LocalStore(tmp_path)), key=lambda row: row["at"])]
    assert steps == ["APPROVED", "STARTED", "LEDGER_REPLACED"]
    assert folder_rows(LocalStore(tmp_path), "payment_events", H06)   # 실제 형식 검사기로 결제 줄을 만들었다
    assert main([], env=env, now=ticking(), log=lambda _: None) == 0   # 끝난 요청은 다시 고르지 않는다
    assert len(read_events(LocalStore(tmp_path))) == 3
