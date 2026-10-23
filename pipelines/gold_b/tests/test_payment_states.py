"""결제 정리 뷰 시험: payment_states(결제마다 마지막 이벤트와 보류 사유)와 이것을 나눠 읽는 payment_attempts·payment_conflicts.

결제 샘플(samples/payments.json, payment_updates.json)을 실제 형식 검사기로 원장 ①·④ 줄로 만든다. 평소 적재 잡이
Kafka 시각 30초 뒤에 쌓았다고 보고, payment_states.json의 rechecks(재처리·다시 쌓기)로 같은 위치의 검사 결과를 더한다.
그 원장에서 views/의 SQL 파일을 그대로 SQLite(파이썬 표준 라이브러리)로 돌려 payment_states.json의 기대 결과와 비교한다.
같은 원장을 로컬 Trino 484(Athena 엔진 3 계열)에서 돌린 확인은 docs/tasks/gold-b-payment-update.md에 적었다.

맨 아래 시험은 재처리 잡(가짜 Kafka, 임시 폴더)으로 원장을 바꾼 뒤 같은 뷰로 결제 상태를 본다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

pytest.importorskip("yaml")
pytest.importorskip("pyarrow")
if sqlite3.sqlite_version_info < (3, 25, 0):
    pytest.skip("창 함수가 없는 SQLite", allow_module_level=True)

from pipelines.gold_b.format_check import DATASETS, FormatChecker  # noqa: E402
from pipelines.gold_b.jobs.reprocess import Request, run  # noqa: E402
from pipelines.gold_b.ledger import (TABLE_COLUMNS, KafkaMessage, LocalStore, hour_folder, hour_of,  # noqa: E402
                                     message_rows, utc_naive)
from test_ddl import SAMPLES as SAMPLE_DIR, _utc, load_payment_updates, load_samples  # noqa: E402
from test_reprocess import FakeKafka, comparable, events as reprocess_events, ticking, write_ledgers  # noqa: E402

VIEWS = Path(__file__).resolve().parent.parent / "views"
VIEW_ORDER = ("payment_states", "payment_conflicts", "payment_attempts")   # 뒤의 두 뷰는 payment_states를 읽는다
TABLES = ("payment_events", "malformed_events")
HOLD_REASONS = {None, "MULTI_PARTITION", "ORDER_ANOMALY", "INVALID_LATEST"}
STREAM_DELAY = timedelta(seconds=30)   # 평소 적재 잡이 쌓는 시각 (Kafka 시각 30초 뒤로 본다)
EXPECTED = json.loads((SAMPLE_DIR / "payment_states.json").read_text(encoding="utf-8"))
SAMPLES = {s["name"]: s for s in load_samples() + load_payment_updates() if s["kafka"]["topic"] == "payments"}


def pid(suffix: str) -> str:
    return f"00000000-4000-8000-0000-0000000000{suffix}"


def message(sample: dict) -> KafkaMessage:
    k = sample["kafka"]
    raw = sample["value_raw"] if "value_raw" in sample else json.dumps(sample["value"], ensure_ascii=False)
    return KafkaMessage(k["topic"], k["partition"], k["offset"], _utc(k["timestamp"]), raw.encode("utf-8"))


class RecheckRules:
    """재처리에 쓴 새 규칙표 흉내. 정해 둔 오류만 낸다 (없으면 모두 통과). only가 있으면 그 값인 줄에만 낸다."""

    def __init__(self, version: str, errors: list[dict], only: dict | None = None):
        self.version = version
        self.datasets = {name: {} for name in DATASETS.values()}
        self._errors = [SimpleNamespace(field=e["field"], code=e["reason"]) for e in errors]
        self._only = only or {}

    def errors(self, dataset, row):
        return list(self._errors) if all(row.get(k) == v for k, v in self._only.items()) else []


def ledgers() -> dict[str, list[dict]]:
    """평소 적재와 재검사로 쌓인 원장 ①·④ 줄."""
    current = FormatChecker()
    rows: dict[str, list[dict]] = {table: [] for table in TABLES}

    def add(sample: dict, checker: FormatChecker, loaded_at: datetime) -> list[dict]:
        judgement = checker(message(sample))
        written = message_rows(message(sample), judgement, checker.rule_version, loaded_at)
        for table in TABLES:
            rows[table].extend(written[table])
        return judgement.errors

    for sample in SAMPLES.values():
        add(sample, current, utc_naive(_utc(sample["kafka"]["timestamp"])) + STREAM_DELAY)
    for recheck in EXPECTED["rechecks"]:
        checker = current if recheck["rule_version"] is None else \
            FormatChecker(RecheckRules(recheck["rule_version"], recheck["errors"]))
        errors = add(SAMPLES[recheck["sample"]], checker, utc_naive(_utc(recheck["loaded_at"])))
        assert [(e["field"], e["reason"]) for e in errors] == \
            [(e["field"], e["reason"]) for e in recheck["errors"]], recheck["description"]
    return rows


def _cell(value: object) -> object:
    """SQLite에 넣는 값. 시각은 자릿수를 맞춘 글자라 글자 순서가 시간 순서다."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f") if isinstance(value, datetime) else value


def run_views(rows: dict[str, list[dict]]) -> sqlite3.Connection:
    """원장 두 개를 SQLite 표로 넣고 views/의 SQL 파일로 뷰 3개를 만든다 (gold_b. 접두어와 OR REPLACE만 뺌)."""
    db = sqlite3.connect(":memory:")
    for table in TABLES:
        names = [name for name, _ in TABLE_COLUMNS[table]]
        db.execute(f"CREATE TABLE {table} ({', '.join(names)})")
        db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(names))})",
                       [[_cell(row[name]) for name in names] for row in rows[table]])
    for name in VIEW_ORDER:
        sql = (VIEWS / f"{name}.sql").read_text(encoding="utf-8")
        db.executescript(sql.replace("CREATE OR REPLACE VIEW", "CREATE VIEW").replace("gold_b.", ""))
    return db


def by_payment(db: sqlite3.Connection, view: str) -> dict[str, dict]:
    cursor = db.execute(f"SELECT * FROM {view}")
    names = [d[0] for d in cursor.description]
    rows = [dict(zip(names, values)) for values in cursor]
    found = {row["payment_id"]: row for row in rows}
    assert len(found) == len(rows), f"{view}: 결제마다 한 줄"
    return found


@pytest.fixture(scope="module")
def result():
    rows = ledgers()
    db = run_views(rows)
    views = {view: by_payment(db, view) for view in VIEW_ORDER}
    db.close()
    return rows, views


def test_expected_file_matches_samples():
    """기대 결과 파일: 키가 있는 결제마다 한 줄, 마지막 이벤트는 그 결제의 샘플. 키를 모르는 오류는 결제와 잇지 않는다."""
    states = EXPECTED["states"]
    ids = [s["payment_id"] for s in states]
    assert len(ids) == len(set(ids))
    for state in states:
        assert SAMPLES[state["latest"]]["value"]["payment_id"] == state["payment_id"]
        assert state["hold_reason"] in HOLD_REASONS
        assert ("failure_cause" in state) == (state["hold_reason"] is None)   # 보류되지 않은 결제만 payment_attempts에 있다
    linked = {s["value"]["payment_id"] for s in SAMPLES.values() if "payment_id" in s.get("value", {})}
    assert set(ids) == linked
    assert all("payment_id" not in SAMPLES[name].get("value", {}) for name in EXPECTED["unlinked"])


def test_payment_states_match_expected(result):
    """결제마다 마지막 이벤트(Kafka 위치), 이벤트 수(위치 수), 보류 사유가 기대 결과와 같다."""
    states = result[1]["payment_states"]
    assert set(states) == {s["payment_id"] for s in EXPECTED["states"]}
    for expected in EXPECTED["states"]:
        got, latest = states[expected["payment_id"]], SAMPLES[expected["latest"]]["kafka"]
        assert (got["kafka_partition"], got["kafka_offset"]) == (latest["partition"], latest["offset"]), expected
        assert (got["event_count"], got["hold_reason"]) == (expected["event_count"], expected["hold_reason"]), expected
        if "rule_version" in expected:
            assert got["rule_version"] == expected["rule_version"]


def test_attempts_show_the_latest_values_of_payments_not_held(result):
    """payment_attempts: 보류되지 않은 결제마다 마지막 이벤트의 값 (수정되었으면 수정된 값)과 실패 원인."""
    attempts = result[1]["payment_attempts"]
    shown = [s for s in EXPECTED["states"] if s["hold_reason"] is None]
    assert set(attempts) == {s["payment_id"] for s in shown}
    for expected in shown:
        got, value = attempts[expected["payment_id"]], SAMPLES[expected["latest"]]["value"]
        for column in ("order_id", "attempt_no", "pg", "status", "failure_code"):
            assert got[column] == value[column], (expected["payment_id"], column)
        assert got["completed_at"] == _cell(utc_naive(_utc(value["completed_at"])))
        assert got["failure_cause"] == expected["failure_cause"], expected["payment_id"]


def test_conflicts_list_held_payments_with_reason(result):
    held = {s["payment_id"]: s["hold_reason"] for s in EXPECTED["states"] if s["hold_reason"]}
    assert {payment: row["hold_reason"] for payment, row in result[1]["payment_conflicts"].items()} == held


def test_ledger_keeps_every_event(result):
    """원장은 바꾸지 않는다. 수정 전후와 재검사 이력이 다 남고, completed_at이 바뀐 u는 새 시간 폴더에 쌓인다."""
    rows = result[0]
    payments = rows["payment_events"]
    assert {(r["kafka_offset"], r["cdc_op"]) for r in payments if r["payment_id"] == pid("51")} == {(1000, "c"), (1001, "u")}
    moved = {r["cdc_op"]: hour_of(r["completed_at"]) for r in payments if r["payment_id"] == pid("58")}
    assert moved == {"c": datetime(2026, 10, 22, 6), "u": datetime(2026, 10, 22, 7)}
    # 재처리로 복구된 위치: 옛 오류(지금 규칙)와 새 통과(새 규칙)가 같은 위치에 함께 있다
    position = (0, 1003)
    errors = [r for r in rows["malformed_events"] if (r["kafka_partition"], r["kafka_offset"]) == position]
    passes = [r for r in payments if (r["kafka_partition"], r["kafka_offset"]) == position]
    assert [(r["record_key"], r["rule_version"]) for r in errors] == [(pid("54"), FormatChecker().rule_version)]
    assert [r["rule_version"] for r in passes] == ["0.3.0-test"]
    # 두 번 쌓은 메시지는 ① 두 줄이지만 이벤트는 1개
    assert sum(r["payment_id"] == pid("5b") for r in payments) == 2


# ---------- 재처리 뒤 결제 상태 (재처리 잡 → 원장 → 뷰) ----------

AFTER = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)   # 재처리하는 시각 (시간 폴더가 다 끝난 뒤)
NEW_RULES = "0.3.0-test"
PG_C_ERROR = [{"field": "pg", "reason": "INVALID_VALUE"}]


def late(name: str, kafka_timestamp: str, offset: int | None = None, value: dict | None = None) -> dict:
    """샘플 메시지가 다른 Kafka 시각(과 위치·값)으로 들어온 경우. 결제 시각보다 늦게 온 수정을 만든다."""
    sample = SAMPLES[name]
    kafka = {**sample["kafka"], "timestamp": kafka_timestamp, "offset": offset or sample["kafka"]["offset"]}
    return {**sample, "kafka": kafka, "value": {**sample["value"], **(value or {})}}


def stream(root: Path, samples: list[dict], name: str = "part-stream.parquet") -> None:
    """평소 적재 잡처럼 지금 규칙으로 검사해 Kafka 시각 30초 뒤에 시간 폴더별로 쌓는다."""
    checker = FormatChecker()
    rows: dict[str, list[dict]] = {table: [] for table in ("payment_events", "topic_messages", "malformed_events")}
    for sample in samples:
        m = message(sample)
        for table, items in message_rows(m, checker(m), checker.rule_version,
                                         utc_naive(m.timestamp) + STREAM_DELAY).items():
            rows[table].extend(items)
    write_ledgers(LocalStore(root), rows, name)


def reprocess(root: Path, samples: list[dict], start: str, end: str, rules: RecheckRules,
              at: datetime = AFTER, store: LocalStore | None = None):
    """새 규칙으로 [start, end)의 시간 폴더를 재처리한다. Kafka에는 samples의 메시지가 있다. run()의 Result를 돌려준다."""
    return run(Request(f"rq-{start}-{at:%H%M}", _utc(start), _utc(end), rules.version),
               source=FakeKafka([message(s) for s in samples]), store=store or LocalStore(root),
               checker=FormatChecker(rules), now=ticking(at), log=lambda _: None)


def hour22(h: int) -> tuple[datetime, datetime]:
    """2026-10-22 h시 폴더 [시작, 끝)."""
    return datetime(2026, 10, 22, h), datetime(2026, 10, 22, h) + timedelta(hours=1)


def replaced_folders(root: Path) -> list[tuple[int, bool]]:
    """LEDGER_REPLACED마다 (시간, 승인 범위 밖인가)."""
    return [(e["window_start"].hour, json.loads(e["detail"]).get("outside_window", False))
            for e in reprocess_events(LocalStore(root)) if e["step"] == "LEDGER_REPLACED"]


LEDGERS = ("payment_events", "topic_messages", "malformed_events")   # 재처리가 고치는 원장 3개


def stored_rows(root: Path, tables: tuple[str, ...] = TABLES) -> dict[str, list[dict]]:
    store = LocalStore(root)
    return {table: [row for path in sorted((root / table).rglob("*.parquet")) if not path.name.startswith(".")
                    for row in store.read(path.relative_to(root).as_posix(), table)]
            for table in tables}


def state_of(root: Path, payment_id: str) -> dict:
    db = run_views(stored_rows(root))
    try:
        return by_payment(db, "payment_states")[payment_id]
    finally:
        db.close()


@pytest.mark.parametrize("still_failing", [False, True])
def test_reprocess_decides_a_bad_latest_update(tmp_path, still_failing):
    """잘못된 최신 u(PG_C)를 새 규칙으로 재처리한다. 통과하면 다시 보이고, 여전히 오류면 보류가 유지된다.
    옛 규칙의 오류 줄은 이력으로 남고, 같은 규칙으로 두 번 재처리해도 검사 결과가 늘지 않는다."""
    samples = [SAMPLES["upd_recovered_c"], SAMPLES["upd_recovered_u"]]
    stream(tmp_path, samples)
    assert state_of(tmp_path, pid("54"))["hold_reason"] == "INVALID_LATEST"

    rules = RecheckRules(NEW_RULES, PG_C_ERROR if still_failing else [], only={"pg": "PG_C"})
    for at in (AFTER, AFTER + timedelta(hours=1)):
        reprocess(tmp_path, samples, "2026-10-22T06:00:00Z", "2026-10-22T07:00:00Z", rules, at)
        got = state_of(tmp_path, pid("54"))
        assert (got["kafka_offset"], got["event_count"], got["rule_version"]) == (1003, 2, NEW_RULES)
        assert got["hold_reason"] == ("INVALID_LATEST" if still_failing else None)

    rows = stored_rows(tmp_path)
    at_u = [r for table in TABLES for r in rows[table] if (r["kafka_partition"], r["kafka_offset"]) == (0, 1003)]
    assert sorted((r["rule_version"], "field" in r) for r in at_u) == \
        [(FormatChecker().rule_version, True), (NEW_RULES, still_failing)]


def test_stricter_rules_clean_the_old_pass_of_a_late_update(tmp_path):
    """통과했던 u(결제 시각 06:10, Kafka 07:30)가 더 엄격한 새 규칙에서 오류가 된다. 07시만 재처리해도 06시 폴더(승인 범위 밖)의
    옛 ① 줄을 지우고 07시에 ④를 쓴다 (옛 결과를 있던 자리까지 찾아 정리, 2026-10-23). 결제는 보류된다."""
    samples = [SAMPLES["upd_normal_c"], late("upd_normal_u", "2026-10-22T07:30:02Z")]
    stream(tmp_path, samples)
    assert state_of(tmp_path, pid("51"))["hold_reason"] is None

    result = reprocess(tmp_path, samples, "2026-10-22T07:00:00Z", "2026-10-22T08:00:00Z",
                       RecheckRules(NEW_RULES, [{"field": "amount", "reason": "INVALID_VALUE"}], only={"amount": 39000}))

    rows = stored_rows(tmp_path)
    assert [r["kafka_offset"] for r in rows["payment_events"]] == [1000]       # c는 대상이 아니라 그대로, u의 옛 통과는 지움
    assert [(r["field"], r["rule_version"]) for r in rows["malformed_events"]] == [("amount", NEW_RULES)]
    assert state_of(tmp_path, pid("51"))["hold_reason"] == "INVALID_LATEST"
    assert (result.replaced, result.outside) == ([hour22(7)], [hour22(6)])
    assert replaced_folders(tmp_path) == [(6, True), (7, False)]


@pytest.mark.parametrize("kafka_time, start, end", [
    ("2026-10-22T07:05:02Z", "2026-10-22T07:00:00Z", "2026-10-22T08:00:00Z"),
    ("2026-10-22T09:41:02Z", "2026-10-22T09:00:00Z", "2026-10-22T10:00:00Z"),
    ("2026-10-23T09:41:02Z", "2026-10-23T09:00:00Z", "2026-10-23T10:00:00Z"),   # 다음 날 들어온 결제 수정
])
def test_late_bad_update_is_recovered_from_its_kafka_hour(tmp_path, kafka_time, start, end):
    """잘못된 u(PG_C)의 결제 시각은 10/22 06:13. 오류가 보이는 Kafka 시각 폴더만 새 규칙(PG_C 허용)으로 재처리해도,
    통과한 ① 줄을 결제 시각 폴더(06시, 승인 범위 밖)에 써서 복구된다. 옛 규칙의 오류 줄은 이력으로 남는다 (2026-10-23)."""
    samples = [SAMPLES["upd_recovered_c"], late("upd_recovered_u", kafka_time)]
    stream(tmp_path, samples)
    assert state_of(tmp_path, pid("54"))["hold_reason"] == "INVALID_LATEST"

    result = reprocess(tmp_path, samples, start, end, RecheckRules(NEW_RULES, []))

    got = state_of(tmp_path, pid("54"))
    assert (got["kafka_offset"], got["hold_reason"], got["pg"], got["rule_version"]) == (1003, None, "PG_C", NEW_RULES)
    assert result.outside == [hour22(6)]
    errors = [r for r in stored_rows(tmp_path)["malformed_events"] if r["kafka_offset"] == 1003]
    assert [r["rule_version"] for r in errors] == [FormatChecker().rule_version]


def test_same_rule_version_fix_shows_the_corrected_value(tmp_path):
    """06:13 실패를 성공으로 바로잡은 u(Kafka 09:41)가 검사 코드 버그로 오류였다. 코드만 고치고 같은 규칙 버전으로
    09시를 재처리하면, 옛 오류를 지우고 통과한 ① 줄을 06시에 써서 정정된 성공이 보인다 (정정 전 실패가 보이지 않음)."""
    version = FormatChecker().rule_version
    c = late("upd_recovered_c", "2026-10-22T06:13:02Z", value={"status": "FAILED", "failure_code": "PG_TIMEOUT"})
    u = late("upd_recovered_u", "2026-10-22T09:41:02Z", value={"pg": "PG_B", "status": "SUCCESS"})
    stream(tmp_path, [c])
    buggy, m = FormatChecker(RecheckRules(version, [{"field": "completed_at", "reason": "TYPE_MISMATCH"}])), message(u)
    write_ledgers(LocalStore(tmp_path), message_rows(m, buggy(m), version, utc_naive(m.timestamp) + STREAM_DELAY),
                  "part-stream-u.parquet")
    assert state_of(tmp_path, pid("54"))["hold_reason"] == "INVALID_LATEST"

    reprocess(tmp_path, [c, u], "2026-10-22T09:00:00Z", "2026-10-22T10:00:00Z", RecheckRules(version, []))

    got = state_of(tmp_path, pid("54"))
    assert (got["kafka_offset"], got["status"], got["failure_code"], got["hold_reason"]) == (1003, "SUCCESS", None, None)
    assert [r for r in stored_rows(tmp_path)["malformed_events"] if r["kafka_offset"] == 1003] == []


def test_messages_outside_the_window_are_left_alone(tmp_path):
    """결제 시각 06:59:59, Kafka 07:00:01인 결제는 06시를 재처리할 때 대상이 아니다 (대상은 Kafka 시각으로 정함).
    더 엄격한 새 규칙으로 06시만 재처리해도 그 결제의 줄은 그대로다 (예전에는 옛 ① 줄만 지워져 뷰에서 사라졌다)."""
    p = late("upd_normal_c", "2026-10-22T07:00:01Z",
             value={"requested_at": "2026-10-22T06:59:55Z", "completed_at": "2026-10-22T06:59:59Z"})
    stream(tmp_path, [p])
    before = stored_rows(tmp_path)

    result = reprocess(tmp_path, [p], "2026-10-22T06:00:00Z", "2026-10-22T07:00:00Z",
                       RecheckRules(NEW_RULES, [{"field": "amount", "reason": "INVALID_VALUE"}]))

    assert stored_rows(tmp_path) == before
    assert state_of(tmp_path, pid("51"))["hold_reason"] is None
    assert (result.replaced, result.outside) == ([hour22(6)], [])


def test_late_update_inside_the_window_needs_no_outside_folder(tmp_path):
    """결제 시각 06:13, Kafka 07:20인 잘못된 u. 06~08시를 같이 재처리하면 06시 폴더도 승인 범위라 범위 밖 폴더 없이 복구된다
    (예전에는 06시 차례에 07:20 메시지를 읽지 않고 07시 차례에 ① 줄을 버려서 복구되지 않았다)."""
    samples = [SAMPLES["upd_recovered_c"], late("upd_recovered_u", "2026-10-22T07:20:02Z")]
    stream(tmp_path, samples)

    result = reprocess(tmp_path, samples, "2026-10-22T06:00:00Z", "2026-10-22T08:00:00Z", RecheckRules(NEW_RULES, []))

    assert state_of(tmp_path, pid("54"))["hold_reason"] is None
    assert (result.replaced, result.outside) == ([hour22(6), hour22(7)], [])


def test_same_request_twice_gives_the_same_ledgers(tmp_path):
    """같은 요청을 두 번 돌려도 범위 밖 폴더까지 원장이 같고(loaded_at만 다름), 고친 폴더는 파일 하나로 정리된다."""
    samples = [SAMPLES["upd_recovered_c"], late("upd_recovered_u", "2026-10-22T09:41:02Z")]
    stream(tmp_path, samples)
    rules = RecheckRules(NEW_RULES, [])
    reprocess(tmp_path, samples, "2026-10-22T09:00:00Z", "2026-10-22T10:00:00Z", rules)
    first = {table: comparable(rows) for table, rows in stored_rows(tmp_path, LEDGERS).items()}

    reprocess(tmp_path, samples, "2026-10-22T09:00:00Z", "2026-10-22T10:00:00Z", rules, at=AFTER + timedelta(hours=1))

    assert {table: comparable(rows) for table, rows in stored_rows(tmp_path, LEDGERS).items()} == first
    store = LocalStore(tmp_path)
    assert len(store.files(hour_folder("payment_events", hour22(6)[0]))) == 1
    assert len(store.files(hour_folder("topic_messages", hour22(9)[0]))) == 1


class CrashBeforeTidyStore(LocalStore):
    """(가)에서 새 줄을 더한 뒤, (나)에서 원장 폴더를 처음 읽을 때 한 번 멈춘다."""

    def __init__(self, root):
        super().__init__(root)
        self.crashed = False

    def files(self, folder, any_name=False):
        if not self.crashed and not folder.startswith("reprocess_events"):
            self.crashed = True
            raise OSError("멈춤 (시험)")
        return super().files(folder, any_name)


def test_stop_after_adding_new_results_loses_nothing(tmp_path):
    """(가) 뒤에 멈추면 같은 위치에 옛 오류와 새 통과가 함께 남아, 뷰는 더 늦게 쌓인 새 결과를 보여 준다.
    다시 돌리면 정리되어 위치마다 결과가 하나다."""
    samples = [SAMPLES["upd_recovered_c"], late("upd_recovered_u", "2026-10-22T09:41:02Z")]
    stream(tmp_path, samples)
    store = CrashBeforeTidyStore(tmp_path)
    with pytest.raises(OSError):
        reprocess(tmp_path, samples, "2026-10-22T09:00:00Z", "2026-10-22T10:00:00Z", RecheckRules(NEW_RULES, []),
                  store=store)
    assert [e["step"] for e in reprocess_events(store)] == ["STARTED", "FAILED"]
    assert state_of(tmp_path, pid("54"))["hold_reason"] is None

    reprocess(tmp_path, samples, "2026-10-22T09:00:00Z", "2026-10-22T10:00:00Z", RecheckRules(NEW_RULES, []),
              at=AFTER + timedelta(hours=1))

    rows = stored_rows(tmp_path, LEDGERS)
    assert len([r for r in rows["payment_events"] if r["kafka_offset"] == 1003]) == 1
    assert len([r for r in rows["topic_messages"] if r["kafka_offset"] == 1003]) == 1
    assert state_of(tmp_path, pid("54"))["hold_reason"] is None
