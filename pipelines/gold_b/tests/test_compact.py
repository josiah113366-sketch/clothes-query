"""파일 합치기 시험. 임시 폴더(LocalStore)에 작은 원장 파일 여러 개를 만들고 합친다."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json

import pytest

pytest.importorskip("pyarrow")

from pipelines.gold_b.jobs.compact import COMPACTED_FROM, CompactError, main, run  # noqa: E402
from pipelines.gold_b.ledger import LocalStore, hour_folder  # noqa: E402

UTC = timezone.utc
DAY = date(2026, 10, 21)
H06, H07 = datetime(2026, 10, 21, 6), datetime(2026, 10, 21, 7)


def after_day():
    return datetime(2026, 10, 22, 1, 0, tzinfo=UTC)


def topic_row(offset: int, loaded_minute: int) -> dict:
    return {"topic": "payments", "kafka_partition": 0, "kafka_offset": offset,
            "kafka_timestamp": datetime(2026, 10, 21, 6, offset), "loaded_at": datetime(2026, 10, 21, 6, loaded_minute)}


def lag_row(minute: int) -> dict:
    return {"collected_at": datetime(2026, 10, 21, 6, minute), "topic": "payments", "kafka_partition": 0,
            "end_offset": 10, "committed_offset": 9, "lag_msgs": 1, "lag_sec": 3.5, "connector_state": "RUNNING"}


def seed(store: LocalStore) -> None:
    """06시: topic_messages 파일 3개(같은 위치가 두 번 쌓인 줄 포함), bronze_lag_snapshots 파일 2개. 07시: 파일 1개."""
    topics = hour_folder("topic_messages", H06)
    store.write(f"{topics}/part-1.parquet", "topic_messages", [topic_row(1, 2), topic_row(2, 2)])
    store.write(f"{topics}/part-2.parquet", "topic_messages", [topic_row(3, 3)])
    store.write(f"{topics}/part-3.parquet", "topic_messages", [topic_row(3, 4)])   # 같은 위치 두 번 (신뢰성 신호)
    lag = hour_folder("bronze_lag_snapshots", H06)
    store.write(f"{lag}/part-a.parquet", "bronze_lag_snapshots", [lag_row(1)])
    store.write(f"{lag}/part-b.parquet", "bronze_lag_snapshots", [lag_row(2)])
    store.write(f"{hour_folder('topic_messages', H07)}/part-1.parquet", "topic_messages", [topic_row(5, 7)])


def rows(store: LocalStore, table: str, hour: datetime) -> Counter:
    """loaded_at까지 포함한 줄 묶음 (같은 줄이 두 번이면 2로 셈)."""
    return Counter(tuple(sorted(row.items())) for path in store.files(hour_folder(table, hour))
                   for row in store.read(path, table))


def test_merges_each_hour_folder_into_one_file_and_keeps_every_row(tmp_path):
    store = LocalStore(tmp_path)
    seed(store)
    before = {table: rows(store, table, H06) for table in ("topic_messages", "bronze_lag_snapshots")}
    single = tmp_path / hour_folder("topic_messages", H07) / "part-1.parquet"
    single_bytes = single.read_bytes()

    done = run(DAY, store=store, now=after_day, log=lambda _: None)

    assert sorted((d["table"], d["files"], d["rows"]) for d in done) == [
        ("bronze_lag_snapshots", 2, 2), ("topic_messages", 3, 4)]
    for table, expected in before.items():
        assert len(store.files(hour_folder(table, H06))) == 1
        assert rows(store, table, H06) == expected
    merged = store.files(hour_folder("topic_messages", H06))[0]
    assert json.loads(store.metadata(merged)[COMPACTED_FROM]) == ["part-1.parquet", "part-2.parquet", "part-3.parquet"]
    assert single.read_bytes() == single_bytes   # 파일이 1개인 폴더는 그대로


def test_refuses_a_day_that_has_not_ended(tmp_path):
    store = LocalStore(tmp_path)
    seed(store)
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))

    with pytest.raises(CompactError):
        run(DAY, store=store, now=lambda: datetime(2026, 10, 22, 0, 5, tzinfo=UTC), log=lambda _: None)

    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet")) == files


class CrashOnceStore(LocalStore):
    """합친 파일을 쓴 뒤 원래 파일을 지우다가 한 번 멈춘다."""

    def __init__(self, root):
        super().__init__(root)
        self.crashed = False

    def delete(self, paths):
        if not self.crashed and paths:
            self.crashed = True
            raise OSError("멈춤 (시험)")
        super().delete(paths)


def test_rerun_after_crash_does_not_double_rows(tmp_path):
    """원래 파일을 못 지우고 멈춘 뒤 다시 돌리면, 이미 합친 원래 파일은 다시 합치지 않고 지운다. 그 사이 들어온 파일은 합친다."""
    store = CrashOnceStore(tmp_path)
    seed(store)
    before = rows(store, "topic_messages", H06)
    folder = hour_folder("topic_messages", H06)

    with pytest.raises(OSError):
        run(DAY, store=store, now=after_day, log=lambda _: None)
    assert len(store.files(folder)) == 4   # 합친 파일 + 못 지운 원래 파일 3개
    late = topic_row(9, 30)
    store.write(f"{folder}/part-late.parquet", "topic_messages", [late])   # 그 사이 늦게 들어온 파일

    run(DAY, store=store, now=after_day, log=lambda _: None)

    assert len(store.files(folder)) == 1
    assert rows(store, "topic_messages", H06) == before + Counter([tuple(sorted(late.items()))])


def test_main_compacts_yesterday_by_default(tmp_path):
    """실행 입구 (python -m pipelines.gold_b.jobs.compact): 날짜를 주지 않으면 어제(UTC)를 합친다."""
    store = LocalStore(tmp_path)
    seed(store)
    assert main([], env={"GOLD_B_LEDGER_ROOT": str(tmp_path)}, now=after_day, log=lambda _: None) == 0
    assert len(store.files(hour_folder("topic_messages", H06))) == 1


def test_main_fails_without_root_or_for_an_unfinished_day(tmp_path):
    logs: list[str] = []
    assert main([], env={}, log=logs.append) == 1
    env = {"GOLD_B_LEDGER_ROOT": str(tmp_path)}
    assert main(["--day", "2026-10-22"], env=env, now=after_day, log=logs.append) == 1
    assert "아직 끝나지 않았다" in logs[-1]
