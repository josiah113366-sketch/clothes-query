import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sim.member.params import AGE_BANDS
from sim.sink import checks, params
from sim.sink.checks import SinkChecker

REGION = "서울특별시 강남구"
TODAY = date(2026, 10, 14)
CREATED = "2026-10-14T04:00:00Z"
SOURCE_TS = 1_791_951_867_690  # 2026-10-14
FAKE_PII = "someone@example.com"
FAKE_SECRET = "FAKESECRETVALUE123"


@dataclass(frozen=True)
class Obj:
    key: str
    size: int = 20_000
    last_modified: datetime = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)


def key(offset: int, partition: int = 0, dt: str = "2026-10-14") -> str:
    year, month, day = dt.split("-")
    folder = f"year={year}/month={month}/day={day}"
    return f"bronze/{params.TOPIC}/{folder}/{params.TOPIC}+{partition}+{offset:010d}.json"


def event(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "member_id": str(uuid.uuid4()),
        "signup_at": "2026-08-15T01:00:00Z",
        "signup_channel": "web",
        "gender": "F",
        "age_band": AGE_BANDS[0],
        "region_sigungu": REGION,
        "marketing_consent": True,
        "status": "ACTIVE",
        "withdrawn_at": None,
        "created_at": CREATED,
        "__op": "r",
        "__source_ts_ms": SOURCE_TS,
        "__source_snapshot": "true",
    }
    row.update(changes)
    return row


def lines(rows: list[dict[str, object]]) -> list[bytes]:
    return [json.dumps(r).encode() for r in rows]


def checker(offsets: dict[int, tuple[int, int]]) -> SinkChecker:
    return SinkChecker(offsets, [REGION], TODAY)


def build(files: list[tuple[Obj, list[bytes]]], offsets: dict[int, tuple[int, int]]):
    sink = checker(offsets)
    ids: set[str] = set()
    for obj, content in files:
        sink.add_file(obj, content)
        for raw in content:
            try:
                member_id = json.loads(raw).get("member_id")
            except (ValueError, AttributeError):
                continue
            if isinstance(member_id, str):
                ids.add(member_id)
    return sink, ids


def good_files() -> tuple[list[tuple[Obj, list[bytes]]], dict[int, tuple[int, int]]]:
    first, second = [event() for _ in range(3)], [event() for _ in range(2)]
    files = [(Obj(key(0)), lines(first)), (Obj(key(3)), lines(second))]
    return files, {0: (0, 5)}


def by_number(results):
    return {r.number: r for r in results}


def test_good_collection_passes_every_check() -> None:
    files, offsets = good_files()
    sink, ids = build(files, offsets)
    results = by_number(sink.results(ids))
    assert sorted(results) == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert all(r.passed for r in results.values()), {n: r.detail for n, r in results.items()}
    assert "중복 0건" in results[9].detail


def test_bad_path_fails_check_2() -> None:
    sink, ids = build([(Obj("bronze/other/file.json"), lines([event()]))], {0: (0, 1)})
    assert not by_number(sink.results(ids))[2].passed


def test_array_file_and_broken_lines_fail_check_3() -> None:
    array = [b"[", json.dumps(event()).encode(), b"]"]
    sink, ids = build([(Obj(key(0)), array)], {0: (0, 1)})
    assert not by_number(sink.results(ids))[3].passed
    sink, ids = build([(Obj(key(0)), [b"{not json", b""])], {0: (0, 1)})
    assert not by_number(sink.results(ids))[3].passed


def test_extra_pii_field_fails_checks_4_and_5() -> None:
    sink, ids = build([(Obj(key(0)), lines([event(email=FAKE_PII)]))], {0: (0, 1)})
    results = by_number(sink.results(ids))
    assert not results[4].passed and not results[5].passed
    assert FAKE_PII not in results[4].detail + results[5].detail


def test_phone_shaped_object_key_fails_check_5() -> None:
    bad_key = f"bronze/{params.TOPIC}/year=2026/month=10/day=14/010-1234-5678.json"
    sink, ids = build([(Obj(bad_key), lines([event()]))], {0: (0, 1)})
    results = by_number(sink.results(ids))
    assert not results[5].passed
    assert "010-1234-5678" not in results[5].detail


def test_time_without_z_fails_check_6() -> None:
    sink, ids = build(
        [(Obj(key(0)), lines([event(created_at="2026-10-14T13:00:00+09:00")]))], {0: (0, 1)}
    )
    assert not by_number(sink.results(ids))[6].passed


def test_folder_date_before_data_date_or_in_future_fails_check_7() -> None:
    early = Obj(key(0, dt="2026-10-13"))
    sink, ids = build([(early, lines([event()]))], {0: (0, 1)})
    assert not by_number(sink.results(ids))[7].passed
    future = Obj(key(0, dt=(TODAY + timedelta(days=2)).isoformat()))
    sink, ids = build([(future, lines([event()]))], {0: (0, 1)})
    assert not by_number(sink.results(ids))[7].passed


def test_gap_fails_check_8_overlap_only_passes_and_is_counted() -> None:
    files = [(Obj(key(0)), lines([event() for _ in range(2)])), (Obj(key(4)), lines([event()]))]
    sink, ids = build(files, {0: (0, 5)})
    assert not by_number(sink.results(ids))[8].passed

    first = [event() for _ in range(3)]
    overlap = [(Obj(key(0)), lines(first)), (Obj(key(2)), lines(first[2:] + [event()]))]
    sink, ids = build(overlap, {0: (0, 4)})
    result = by_number(sink.results(ids))[8]
    assert result.passed and "겹친 구간 1건" in result.detail


def test_missing_tail_fails_check_8() -> None:
    sink, ids = build([(Obj(key(0)), lines([event() for _ in range(2)]))], {0: (0, 5)})
    assert not by_number(sink.results(ids))[8].passed


def test_fewer_rows_than_topic_fails_check_9_more_passes_with_duplicates() -> None:
    sink, ids = build([(Obj(key(0)), lines([event()]))], {0: (0, 3)})
    assert not by_number(sink.results(ids))[9].passed
    rows = [event(), event()]
    sink, ids = build([(Obj(key(0)), lines(rows + rows[:1]))], {0: (0, 2)})
    result = by_number(sink.results(ids))[9]
    assert result.passed and "중복 1건" in result.detail


def test_member_id_mismatch_fails_check_10() -> None:
    files, offsets = good_files()
    sink, ids = build(files, offsets)
    other = ids | {str(uuid.uuid4())}
    assert not by_number(sink.results(other))[10].passed


def test_many_small_files_only_warn_in_check_11() -> None:
    small = [(Obj(key(i), size=100), lines([event()])) for i in range(3)]
    sink, ids = build(small, {0: (0, 3)})
    result = by_number(sink.results(ids))[11]
    assert result.passed and "경고" in result.detail


def test_failure_output_has_no_pii_or_credentials() -> None:
    sink, ids = build(
        [(Obj(key(0)), lines([event(email=FAKE_PII, password_hash="$2b$12$abc")]))], {0: (0, 1)}
    )
    text = " ".join(r.detail for r in sink.results(ids))
    assert FAKE_PII not in text and "$2b$12$abc" not in text and FAKE_SECRET not in text


# --- 커넥터 상태, 진행 중 판단 ---


def test_check_connector() -> None:
    running = {"connector": {"state": "RUNNING"}, "tasks": [{"state": "RUNNING"}]}
    cfg = {"topics": params.TOPIC}
    assert checks.check_connector(running, cfg, params.TOPIC).passed
    assert not checks.check_connector(None, None, params.TOPIC).passed
    assert not checks.check_connector(running, {"topics": "other"}, params.TOPIC).passed
    failed = {"connector": {"state": "RUNNING"}, "tasks": [{"state": "FAILED"}]}
    assert not checks.check_connector(failed, cfg, params.TOPIC).passed


def test_writing_in_progress() -> None:
    now = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    old = now - timedelta(seconds=params.QUIET_SECONDS + 5)
    recent = now - timedelta(seconds=5)
    assert checks.writing_in_progress(None, old, now) is not None
    assert checks.writing_in_progress(10, old, now) is not None
    assert checks.writing_in_progress(0, recent, now) is not None
    assert checks.writing_in_progress(0, old, now) is None


# --- 커넥터 설정 안전장치 ---


def _good_config() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "connectors" / "member-s3-sink.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"topics": "other-events"}, "topics"),
        ({"aws.access.key.id": "x"}, "자격 증명"),
        ({"note": "AKIA" + "A" * 16}, "AKIA"),
        ({"s3.bucket.name": "literal-bucket"}, "s3.bucket.name"),
        ({"timezone": "Asia/Seoul"}, "timezone"),
        ({"path.format": "YYYY-MM-dd"}, "path.format"),
        (
            {"partitioner.class": "io.confluent.connect.storage.partitioner.DefaultPartitioner"},
            "시간 기반",
        ),
        ({"format.class": "io.confluent.connect.s3.format.avro.AvroFormat"}, "JSON"),
    ],
)
def test_config_problems_catch_each_violation(change: dict[str, str], expected: str) -> None:
    problems = checks.config_problems({**_good_config(), **change}, params.TOPIC)
    assert any(expected in p for p in problems), problems


def test_repo_config_passes_safety() -> None:
    assert checks.config_problems(_good_config(), params.TOPIC) == []


def test_parse_key() -> None:
    parsed = checks.parse_key(key(30, partition=2))
    assert parsed is not None and parsed.partition == 2 and parsed.start_offset == 30
    assert checks.parse_key("bronze/x/year=2026/month=13/day=99/a.json") is None


# --- 레포 전체 ---


def test_no_credential_strings_in_tracked_or_new_files() -> None:
    root = Path(__file__).resolve().parents[2]
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    pattern = re.compile(params.CREDENTIAL_PATTERN)
    offenders = []
    for name in listed:
        path = root / name
        if path.suffix in {".csv", ".png", ".zip"} or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            offenders.append(name)
    assert offenders == []
