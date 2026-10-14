import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sim.cdc import params
from sim.cdc.connect import (
    ConfigFileError,
    ConnectClient,
    ConnectError,
    check_connector_config,
    config_problems,
    is_running,
    load_connector_config,
    wait_running,
)
from sim.cli import app

CONFIG_PATH = Path(__file__).resolve().parents[2] / "connectors" / "member-source.json"
runner = CliRunner()


def _good() -> dict[str, str]:
    return load_connector_config(CONFIG_PATH)


def test_repo_config_passes_safety_check_and_matches_params() -> None:
    config = _good()
    check_connector_config(config)
    names = {c.removeprefix("public.members.") for c in config["column.include.list"].split(",")}
    assert names == set(params.BRONZE_COLUMNS)
    assert config["name"] == params.CONNECTOR_NAME
    assert config["slot.name"] == params.SLOT_NAME
    assert config["publication.name"] == params.PUBLICATION_NAME
    assert config["transforms.route.replacement"] == params.TOPIC


def _with(**changes: object) -> dict:
    config = dict(_good())
    for key, value in changes.items():
        key = key.replace("__", ".")
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    return config


@pytest.mark.parametrize(
    ("config", "needle"),
    [
        (
            _with(column__include__list=_good()["column.include.list"] + ",public.members.email"),
            "더 있음",
        ),
        (
            _with(
                column__include__list=_good()["column.include.list"].replace(
                    ",public.members.status", ""
                )
            ),
            "모자람",
        ),
        (_with(column__exclude__list="public.members.email"), "exclude.list"),
        (_with(column__include__list=None), "include.list가 없습니다"),
        (_with(database__password="plain-text-pw"), "평문"),
        (_with(database__password="${file:/x}"), "평문"),
        (_with(table__include__list="public.members,public.members_archive"), "table.include.list"),
        (_with(column__include__list="member_id,status"), "형태"),
    ],
)
def test_bad_configs_are_rejected(config: dict, needle: str) -> None:
    problems = config_problems(config)
    assert problems and any(needle in p for p in problems)
    with pytest.raises(ConfigFileError):
        check_connector_config(config)


def test_problem_messages_do_not_echo_password() -> None:
    problems = config_problems(_with(database__password="super-secret-pw"))
    assert "super-secret-pw" not in "\n".join(problems)


# --- REST 클라이언트 (가짜 전송) ---


class FakeConnect:
    def __init__(self, responses: list[tuple[int, object]] | None = None) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.responses = responses or []

    def __call__(self, method: str, url: str, body):
        self.calls.append((method, url, body))
        return self.responses.pop(0) if self.responses else (200, None)


def test_create_sends_name_and_flat_config_without_name_inside() -> None:
    transport = FakeConnect([(201, {})])
    ConnectClient("http://c:8083/", transport).create(_good())
    method, url, body = transport.calls[0]
    assert (method, url) == ("POST", "http://c:8083/connectors")
    assert body["name"] == "member-source" and "name" not in body["config"]
    assert body["config"]["database.password"] == "${env:CDC_DB_PASSWORD}"


def test_http_error_becomes_connect_error_with_short_message() -> None:
    transport = FakeConnect([(409, {"message": "x" * 1000})])
    with pytest.raises(ConnectError) as info:
        ConnectClient("http://c", transport).create(_good())
    assert "409" in str(info.value) and len(str(info.value)) < 400


def test_reset_calls_stop_then_offsets_then_delete_in_order() -> None:
    transport = FakeConnect()
    client = ConnectClient("http://c", transport)
    client.stop("n")
    client.delete_offsets("n")
    client.delete("n")
    assert [(m, u.removeprefix("http://c")) for m, u, _ in transport.calls] == [
        ("PUT", "/connectors/n/stop"),
        ("DELETE", "/connectors/n/offsets"),
        ("DELETE", "/connectors/n"),
    ]


def _status(connector: str, *tasks: str) -> dict:
    return {"connector": {"state": connector}, "tasks": [{"state": t} for t in tasks]}


def test_is_running_requires_connector_and_every_task() -> None:
    assert is_running(_status("RUNNING", "RUNNING"))
    assert not is_running(_status("RUNNING"))  # task가 아직 없다
    assert not is_running(_status("RUNNING", "RUNNING", "FAILED"))
    assert not is_running(_status("PAUSED", "RUNNING"))


def test_wait_running_polls_until_running() -> None:
    transport = FakeConnect(
        [(404, None), (200, _status("RUNNING")), (200, _status("RUNNING", "RUNNING"))]
    )
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    result = wait_running(
        ConnectClient("http://c", transport), "n", 60, sleep=sleep, clock=lambda: now[0]
    )
    assert is_running(result) and slept == [1, 1]


def test_wait_running_gives_up_at_timeout_and_stops_on_failure() -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    transport = FakeConnect([(200, _status("RUNNING"))] * 100)
    result = wait_running(
        ConnectClient("http://c", transport), "n", 5, sleep=sleep, clock=lambda: now[0]
    )
    assert not is_running(result) and now[0] == 5

    transport = FakeConnect([(200, _status("RUNNING", "FAILED"))])
    result = wait_running(ConnectClient("http://c", transport), "n", 60, sleep=sleep)
    assert result["tasks"][0]["state"] == "FAILED"


# --- CLI: 거부 동작 (Connect를 부르지 않는다) ---


class NeverCalled:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("Connect를 부르면 안 된다")


def test_reset_refuses_non_local_database_without_calling_connect(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@prod-db.example.net:5432/clothes")
    monkeypatch.setattr("sim.cdc.cli.ConnectClient", NeverCalled)
    result = runner.invoke(app, ["cdc", "reset", "--yes"])
    assert result.exit_code == 1
    assert "로컬" in result.output
    assert "prod-db.example.net" not in result.output


def test_setup_refuses_bad_config_without_calling_connect(monkeypatch, tmp_path: Path) -> None:
    bad = dict(_good(), **{"database.password": "plain"})
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@localhost:5432/clothes")
    monkeypatch.setattr("sim.cdc.cli.ConnectClient", NeverCalled)
    result = runner.invoke(app, ["cdc", "setup", "--config", str(path)])
    assert result.exit_code == 1
    assert "등록하지 않았습니다" in result.output
    assert "plain" not in result.output
