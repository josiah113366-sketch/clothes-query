from pathlib import Path
from typing import ClassVar

import pytest
from behavior_fixtures import StaticCatalog, StaticMembers, make_catalog, make_member_ids
from typer.testing import CliRunner

import sim.behavior.cli as behavior_cli
from sim.behavior.kafka_sink import ClickSinkError, ClickStats
from sim.behavior.sink import MemoryClickSink, MemoryOrderSink
from sim.cli import app

runner = CliRunner()
LOCAL = "postgresql://u:pw@localhost:5432/clothes"


def test_help_lists_options() -> None:
    result = runner.invoke(app, ["behavior", "live", "--help"])
    assert result.exit_code == 0
    for option in (
        "--mode",
        "--visits-daily",
        "--speed",
        "--duration",
        "--max-visits",
        "--control-file",
        "--seed",
        "--run-salt",
        "--click-sink",
        "--click-file",
    ):
        assert option in result.output


def test_refuses_remote_db_without_switch(monkeypatch) -> None:
    host, password = "prod-db.internal.example.net", "s3cr3t-pw"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{password}@{host}:5432/clothes")
    monkeypatch.delenv("SIM_ALLOW_REMOTE_DB", raising=False)
    result = runner.invoke(app, ["behavior", "live", "--max-visits", "1"])
    assert result.exit_code == 1
    assert "SIM_ALLOW_REMOTE_DB=1" in result.output
    assert host not in result.output and password not in result.output


@pytest.mark.parametrize("args", [["--mode", "surge"], ["--click-sink", "s3"]])
def test_rejects_bad_choices(monkeypatch, args) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    result = runner.invoke(app, ["behavior", "live", *args])
    assert result.exit_code == 1


def test_run_prints_start_and_summary_without_pii(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setattr(behavior_cli, "DbOrderSink", lambda url: MemoryOrderSink())
    monkeypatch.setattr(
        behavior_cli, "DbMemberSource", lambda url: StaticMembers(make_member_ids(200))
    )
    monkeypatch.setattr(
        behavior_cli, "DbCatalogSource", lambda url: StaticCatalog(make_catalog(100))
    )
    click_file = tmp_path / "clicks.jsonl"
    result = runner.invoke(
        app,
        [
            "behavior",
            "live",
            "--mode",
            "burst",
            "--speed",
            "3600",
            "--max-visits",
            "30",
            "--run-salt",
            "7",
            "--click-sink",
            "jsonl",
            "--click-file",
            str(click_file),
            "--control-file",
            str(tmp_path / "none.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "대상 DB: localhost:5432/clothes" in out and "pw" not in out
    assert "run_salt: 7" in out and "회원: 200명  상품: 100개" in out
    assert "총 방문: 30건" in out
    assert "example.com" not in out and "010-" not in out
    assert click_file.exists()


class FakeKafkaSink(MemoryClickSink):
    instances: ClassVar[list["FakeKafkaSink"]] = []
    ready_error: ClassVar[str | None] = None

    def __init__(self, settings, warn=None) -> None:
        super().__init__()
        self.closed = 0
        FakeKafkaSink.instances.append(self)

    def check_ready(self) -> None:
        if FakeKafkaSink.ready_error:
            raise ClickSinkError(FakeKafkaSink.ready_error)

    def close(self) -> None:
        self.closed += 1

    @property
    def stats(self) -> ClickStats:
        return ClickStats(sent=len(self.events), failed=0)


def _patch_sources(monkeypatch) -> list[MemoryOrderSink]:
    created: list[MemoryOrderSink] = []

    def order_sink(url: str) -> MemoryOrderSink:
        created.append(MemoryOrderSink())
        return created[-1]

    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setattr(behavior_cli, "DbOrderSink", order_sink)
    monkeypatch.setattr(
        behavior_cli, "DbMemberSource", lambda url: StaticMembers(make_member_ids(200))
    )
    monkeypatch.setattr(
        behavior_cli, "DbCatalogSource", lambda url: StaticCatalog(make_catalog(100))
    )
    monkeypatch.setattr(behavior_cli, "KafkaClickSink", FakeKafkaSink)
    FakeKafkaSink.instances = []
    FakeKafkaSink.ready_error = None
    return created


KAFKA_RUN = ["behavior", "live", "--speed", "3600", "--max-visits", "30", "--run-salt", "7"]


@pytest.mark.parametrize("use_env", [False, True])
def test_kafka_click_sink_by_option_or_env(monkeypatch, tmp_path: Path, use_env: bool) -> None:
    _patch_sources(monkeypatch)
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "localhost:29092")
    args = [*KAFKA_RUN, "--control-file", str(tmp_path / "none.json")]
    if use_env:
        monkeypatch.setenv("SIM_CLICK_SINK", "kafka")
    else:
        monkeypatch.delenv("SIM_CLICK_SINK", raising=False)
        args += ["--click-sink", "kafka"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(FakeKafkaSink.instances) == 1
    sink = FakeKafkaSink.instances[0]
    assert sink.events and sink.closed == 1
    assert "클릭 Sink: kafka (topic clickstream)" in result.output
    assert f"클릭 발행: 성공 {len(sink.events):,}건, 실패 0건" in result.output
    assert "29092" not in result.output


def test_bad_env_click_sink_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.setenv("SIM_CLICK_SINK", "s3")
    result = runner.invoke(app, ["behavior", "live", "--max-visits", "1"])
    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("bootstrap", "hint"), [("localhost:29092", True), ("kafka.example.internal:9093", False)]
)
def test_kafka_not_ready_does_not_start(monkeypatch, tmp_path: Path, bootstrap, hint) -> None:
    created = _patch_sources(monkeypatch)
    monkeypatch.setenv("KAFKA_BOOTSTRAP", bootstrap)
    FakeKafkaSink.ready_error = "토픽 clickstream이(가) 없습니다."
    result = runner.invoke(
        app, [*KAFKA_RUN, "--click-sink", "kafka", "--control-file", str(tmp_path / "n.json")]
    )
    assert result.exit_code == 1
    assert "토픽 clickstream" in result.output
    assert ("sim clickstream setup" in result.output) is hint
    assert "example.internal" not in result.output
    assert created == []  # 방문을 시작하지 않았다
    assert FakeKafkaSink.instances[0].closed == 1
