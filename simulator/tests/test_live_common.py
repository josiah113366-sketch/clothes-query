import json
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from sim.common.clock import FakeTime, SimClock
from sim.common.control import ControlState, FileControlSource
from sim.common.db import DbErrorInfo, db_error_info, describe_db_error
from sim.common.rng import SimRandom, derive_seed
from sim.member.params import KST

PII = "hong.gildong@secret-mail.com 010-1234-5678"
START = datetime(2026, 10, 1, 0, 0, 0, tzinfo=KST)


# --- derive_seed / reseed ---


def test_derive_seed_is_deterministic_and_distinct() -> None:
    assert derive_seed(42, "live", 3) == derive_seed(42, "live", 3)
    values = {derive_seed(42, "live", k) for k in range(1000)}
    assert len(values) == 1000
    assert derive_seed(42, "live", 1) != derive_seed(43, "live", 1)
    assert derive_seed(42, "live", 1) != derive_seed(42, "other", 1)
    assert derive_seed(42, "a", "bc") != derive_seed(42, "ab", "c")
    assert derive_seed(42, "live", 0) != 42


def test_sim_random_unchanged_and_reseed_matches_fresh() -> None:
    # 기존 SimRandom(42)의 결과 고정값 (이 브랜치 전후로 같아야 한다)
    rng = SimRandom(42)
    assert rng.random.random() == __import__("random").Random(42).random()
    fresh = SimRandom(7)
    reused = SimRandom(42)
    reused.randint(0, 10)
    reused.uuid4()
    reused.reseed(7)
    assert reused.seed == 7
    assert [reused.uuid4(), reused.randint(0, 999), reused.name("F")] == [
        fresh.uuid4(),
        fresh.randint(0, 999),
        fresh.name("F"),
    ]


# --- SimClock ---


def test_clock_speed_one_matches_real_time() -> None:
    ft = FakeTime(START)
    clock = SimClock.fake(ft)
    assert clock.now() == START
    clock.sleep(90)
    assert clock.now() == START + timedelta(seconds=90)
    assert clock.now().utcoffset() == timedelta(hours=9)


def test_clock_speed_and_elapsed() -> None:
    ft = FakeTime(START)
    clock = SimClock.fake(ft, speed=1440)
    clock.sleep(60)
    assert clock.real_elapsed() == 60
    assert clock.now() == START + timedelta(days=1)


def test_clock_restart_resets_origin() -> None:
    ft = FakeTime(START)
    clock = SimClock.fake(ft, speed=60)
    clock.sleep(10)
    clock.restart()
    assert clock.real_elapsed() == 0
    assert clock.now() == START + timedelta(seconds=10)  # 시작 시각은 지금으로 옮겨진다


def test_clock_converts_to_kst_and_rejects_bad_speed() -> None:
    utc = datetime(2026, 9, 30, 15, 0, 0, tzinfo=KST).astimezone(__import__("datetime").UTC)
    clock = SimClock.fake(FakeTime(utc))
    assert clock.now().utcoffset() == timedelta(hours=9)
    with pytest.raises(ValueError):
        SimClock(speed=0)
    with pytest.raises(ValueError):
        FakeTime(datetime(2026, 10, 1))


# --- FileControlSource ---


def _source(tmp_path: Path) -> tuple[FileControlSource, list[str], Path]:
    warnings: list[str] = []
    path = tmp_path / "control.json"
    return FileControlSource(path, warn=warnings.append), warnings, path


def test_control_reads_valid_file(tmp_path: Path) -> None:
    source, warnings, path = _source(tmp_path)
    path.write_text(json.dumps({"running": True, "mode": "surge"}))
    assert source.read() == ControlState(running=True, mode="surge")
    path.write_text(json.dumps({"running": False, "mode": "normal"}))
    assert source.read() == ControlState(running=False, mode="normal")
    assert warnings == []


@pytest.mark.parametrize(
    "content",
    [
        None,  # 파일 없음
        "{not json",
        "[1, 2]",
        '{"running": "yes", "mode": "normal"}',
        '{"running": true, "mode": "turbo"}',
        '{"running": true}',
    ],
)
def test_control_bad_input_returns_none_and_warns_once(tmp_path: Path, content) -> None:
    source, warnings, path = _source(tmp_path)
    if content is not None:
        path.write_text(content)
    assert [source.read() for _ in range(3)] == [None, None, None]
    assert len(warnings) == 1
    assert "turbo" not in warnings[0] and "not json" not in warnings[0]


def test_control_warns_again_after_recovery(tmp_path: Path) -> None:
    source, warnings, path = _source(tmp_path)
    assert source.read() is None
    path.write_text('{"running": true, "mode": "normal"}')
    assert source.read() is not None
    path.write_text("broken")
    assert source.read() is None
    assert len(warnings) == 2


# --- db_error_info ---


class _PiiDiag:
    constraint_name = "member_phone_key"

    @property
    def message_detail(self) -> str:
        raise AssertionError("message_detail을 읽으면 안 된다")


class _PiiError(psycopg.errors.UniqueViolation):
    """메시지·상세에 PII가 든 가짜 오류. str()과 message_detail을 읽으면 테스트가 실패한다."""

    @property
    def diag(self):  # type: ignore[override]
        return _PiiDiag()

    def __str__(self) -> str:
        raise AssertionError("str(error)를 읽으면 안 된다")


def test_db_error_info_returns_only_constraint_and_sqlstate() -> None:
    error = _PiiError(f"Key (phone)=({PII}) already exists.")
    info = db_error_info(error)
    assert info == DbErrorInfo(sqlstate="23505", constraint="member_phone_key")
    assert PII not in repr(info)


def test_db_error_info_without_constraint() -> None:
    info = db_error_info(psycopg.OperationalError(f"server closed {PII}"))
    assert info == DbErrorInfo(sqlstate=None, constraint=None)
    assert PII not in describe_db_error(psycopg.OperationalError(f"server closed {PII}"))
