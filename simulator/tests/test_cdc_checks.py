import json
from datetime import UTC, datetime, timedelta

from sim.cdc import params
from sim.cdc.checks import (
    EventChecker,
    check_connector,
    check_db_side,
    compare_member_ids,
    compare_sample,
)
from sim.cdc.connect import load_connector_config

REGIONS = ["서울특별시 종로구", "부산광역시 중구"]
EMAIL = "user_0123456789abcdef@example.com"
PHONE = "010-1234-5678"
BASE = datetime(2026, 8, 15, 3, 0, 0, tzinfo=UTC)


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _event(n: int, op: str = "r", **changes) -> dict:
    event = {
        "member_id": _uuid(n),
        "signup_at": (BASE + timedelta(minutes=n)).strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "signup_channel": "app",
        "gender": "F",
        "age_band": "20s",
        "region_sigungu": REGIONS[n % 2],
        "marketing_consent": True,
        "status": "ACTIVE",
        "withdrawn_at": None,
        "created_at": "2026-10-13T01:00:00.000000Z",
        "__op": op,
        "__source_ts_ms": 1_760_000_000_000 + n,
        "__source_snapshot": "true" if op == "r" else "false",
    }
    event.update(changes)
    return event


def _feed(checker: EventChecker, events: list[dict], key_of=None) -> None:
    for event in events:
        key = {"member_id": event["member_id"]} if key_of is None else key_of(event)
        checker.add(json.dumps(key).encode(), json.dumps(event, ensure_ascii=False).encode())


def _checker(events: list[dict], **kwargs) -> EventChecker:
    kwargs.setdefault("snapshot_expected", sum(1 for e in events if e["__op"] == "r"))
    checker = EventChecker(REGIONS, **kwargs)
    _feed(checker, events)
    return checker


def _failed(checker: EventChecker) -> set[int]:
    return {r.number for r in checker.results() if not r.passed}


def _good_events() -> list[dict]:
    return [_event(n) for n in range(20)] + [_event(100 + n, "c") for n in range(5)]


def test_clean_events_pass_everything() -> None:
    checker = _checker(_good_events(), live_expected=5)
    assert _failed(checker) == set()
    assert {r.number for r in checker.results()} == {3, 4, 5, 6, 7, 8, 9, 10, 13}


def test_live_expected_is_skipped_when_not_given_and_checked_when_given() -> None:
    skipped = next(r for r in _checker(_good_events()).results() if r.number == 13)
    assert skipped.skipped and skipped.passed
    assert _failed(_checker(_good_events(), live_expected=6)) == {13}


def test_extra_pii_field_fails_fields_and_pii() -> None:
    events = _good_events()
    events[3]["email"] = EMAIL
    checker = _checker(events)
    assert {4, 5} <= _failed(checker)


def test_phone_shaped_value_fails_pii_only_where_expected() -> None:
    events = _good_events()
    events[2]["region_sigungu"] = PHONE
    assert 5 in _failed(_checker(events))


def test_phone_lookalike_inside_a_uuid_is_not_pii_but_a_real_phone_next_to_it_is() -> None:
    # 실제로 걸린 경우: member_id의 일부가 010-숫자4-숫자4 모양
    lookalike = "5c3ba010-1234-4567-8abc-0123456789ab"
    events = [_event(1, member_id=lookalike), _event(2)]
    assert 5 not in _failed(_checker(events))
    events = [_event(1, member_id=lookalike), _event(2, region_sigungu=f"{lookalike} {PHONE}")]
    assert 5 in _failed(_checker(events))


def test_snapshot_first_value_is_accepted_for_r_only() -> None:
    events = _good_events()
    events[0]["__source_snapshot"] = "first"
    assert 9 not in _failed(_checker(events))
    events = _good_events()
    events[21]["__source_snapshot"] = "first"
    assert 9 in _failed(_checker(events))


def test_password_hash_prefix_and_example_com_fail_pii() -> None:
    events = _good_events()
    events[0]["gender"] = "$2b$12$abcdefghijklmnopqrstuv"
    events[1]["signup_channel"] = "someone@example.com"
    assert 5 in _failed(_checker(events))


def test_missing_field_fails_fields() -> None:
    events = _good_events()
    del events[4]["status"]
    assert 4 in _failed(_checker(events))


def test_times_must_be_utc_z() -> None:
    for bad in ("2026-08-15T12:00:00+09:00", "2026-08-15T12:00:00", "not-a-time", 12345):
        events = _good_events()
        events[5]["signup_at"] = bad
        assert 6 in _failed(_checker(events)), bad
    events = _good_events()
    events[5]["withdrawn_at"] = "2026-09-01T00:00:00+09:00"
    assert 6 in _failed(_checker(events))
    events = _good_events()
    events[5]["withdrawn_at"] = "2026-09-01T00:00:00.000000Z"  # 값이 있어도 Z면 통과
    assert 6 not in _failed(_checker(events))


def test_snapshot_signup_at_range_is_utc_not_kst() -> None:
    events = _good_events()
    events[0]["signup_at"] = "2026-09-30T15:00:00.000000Z"  # KST 10/1 00:00, 범위 밖
    assert 6 in _failed(_checker(events))
    events = _good_events()
    events[0]["signup_at"] = "2026-07-31T14:59:59.000000Z"
    assert 6 in _failed(_checker(events))
    events = _good_events()
    events[0]["signup_at"] = "2026-07-31T15:00:00.000000Z"  # 경계 포함
    assert 6 not in _failed(_checker(events))


def test_delete_event_fails_ops() -> None:
    events = _good_events() + [_event(900, "d", __source_snapshot="false")]
    assert 3 in _failed(_checker(events))


def test_snapshot_count_must_match_expected() -> None:
    assert 3 in _failed(_checker(_good_events(), snapshot_expected=21))


def test_duplicate_r_and_duplicate_c_fail() -> None:
    assert 10 in _failed(_checker(_good_events() + [_event(3)], snapshot_expected=21))
    assert 10 in _failed(_checker(_good_events() + [_event(102, "c")]))


def test_key_and_value_member_id_must_match() -> None:
    checker = EventChecker(REGIONS, snapshot_expected=2)
    _feed(
        checker,
        [_event(1), _event(2)],
        key_of=lambda e: (
            {"member_id": _uuid(99)}
            if e["member_id"] == _uuid(2)
            else {"member_id": e["member_id"]}
        ),
    )
    assert _failed(checker) == {8}


def test_snapshot_flag_must_follow_op() -> None:
    events = _good_events()
    events[0]["__source_snapshot"] = "false"
    assert 9 in _failed(_checker(events))
    events = _good_events()
    events[21]["__source_snapshot"] = "true"
    assert 9 in _failed(_checker(events))
    events = _good_events()
    events[19]["__source_snapshot"] = "last"  # 스냅샷의 마지막 행
    assert 9 not in _failed(_checker(events))


def test_c_event_snapshot_flag_may_be_null_as_debezium_emits() -> None:
    events = _good_events()
    for event in events:
        if event["__op"] == "c":
            event["__source_snapshot"] = None
    assert 9 not in _failed(_checker(events))
    events[0]["__source_snapshot"] = None  # r인데 null이면 실패
    assert 9 in _failed(_checker(events))
    events = _good_events()
    events[21]["__source_snapshot"] = "true"  # c인데 스냅샷이면 실패
    assert 9 in _failed(_checker(events))


def test_value_shapes() -> None:
    for field, bad in [
        ("member_id", "not-a-uuid"),
        ("gender", "X"),
        ("signup_channel", "kiosk"),
        ("age_band", "80s"),
        ("status", "DELETED"),
        ("marketing_consent", "yes"),
        ("region_sigungu", "없는 지역"),
        ("__source_ts_ms", "1760000000000"),
    ]:
        events = _good_events()
        events[7][field] = bad
        assert 7 in _failed(_checker(events)), field


def test_not_json_fails_fields() -> None:
    checker = EventChecker(REGIONS, snapshot_expected=0)
    checker.add(b"{}", b"{not json")
    assert 4 in _failed(checker)


def test_failure_output_never_contains_injected_pii() -> None:
    events = _good_events()
    events[1]["email"] = EMAIL
    events[2]["phone"] = PHONE
    events[3]["password_hash"] = "$2b$12$secretsecretsecret"
    events[4]["gender"] = EMAIL
    events[5]["name"] = "홍길동"
    checker = _checker(events)
    text = "\n".join(f"{r.name} {r.detail}" for r in checker.results())
    for secret in (EMAIL, PHONE, "$2b$12$secretsecretsecret", "홍길동", "secretsecret"):
        assert secret not in text
    assert "email" in text  # 필드 이름은 보여 준다


def test_odd_field_names_are_not_echoed() -> None:
    events = _good_events()
    events[0]["홍길동@x.com"] = 1
    text = "\n".join(r.detail for r in _checker(events).results())
    assert "홍길동" not in text and "x.com" not in text


def test_memory_stays_small_only_ids_and_samples_are_kept() -> None:
    sample = {_uuid(3), _uuid(4)}
    checker = _checker(_good_events(), sample_ids=sample)
    assert set(checker.sample_events) == sample
    assert len(checker.all_ids) == 25


# --- DB·Connect와 대조하는 항목 ---


def test_compare_member_ids() -> None:
    ids = {_uuid(n) for n in range(5)}
    assert compare_member_ids(ids, ids).passed
    result = compare_member_ids(ids, ids | {_uuid(9)})
    assert not result.passed and _uuid(9) in result.detail
    assert not compare_member_ids(ids | {_uuid(8)}, ids).passed


def _db_row(n: int) -> dict:
    return {
        "signup_at": BASE + timedelta(minutes=n),
        "created_at": datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC).astimezone(
            datetime.now().astimezone().tzinfo
        ),
        "region_sigungu": REGIONS[n % 2],
        "age_band": "20s",
        "status": "ACTIVE",
    }


def test_compare_sample_compares_instants_not_strings() -> None:
    events = {_uuid(n): _event(n, created_at="2026-10-13T10:00:00Z") for n in range(3)}
    rows = {_uuid(n): _db_row(n) for n in range(3)}
    assert compare_sample(events, rows).passed
    # 시각이 9시간 어긋나면(UTC 변환 오류) 실패
    events[_uuid(1)]["signup_at"] = (BASE + timedelta(minutes=1, hours=9)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = compare_sample(events, rows)
    assert not result.passed and "signup_at" in result.detail
    # 값이 다르거나 이벤트가 없어도 실패
    events = {_uuid(n): _event(n, created_at="2026-10-13T10:00:00Z") for n in range(3)}
    events[_uuid(2)]["status"] = "WITHDRAWN"
    assert not compare_sample(events, rows).passed
    del events[_uuid(0)]
    assert "이벤트 없음" in compare_sample(events, rows).detail
    assert not compare_sample({}, {}).passed


def test_check_connector_and_db_side() -> None:
    good_config = load_connector_config(
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "connectors"
        / "member-source.json"
    )
    running = {"connector": {"state": "RUNNING"}, "tasks": [{"state": "RUNNING"}]}
    assert check_connector(running, good_config).passed
    assert not check_connector(None, None).passed
    assert not check_connector(
        {"connector": {"state": "RUNNING"}, "tasks": [{"state": "FAILED"}]}, good_config
    ).passed
    leaky = dict(
        good_config,
        **{"column.include.list": good_config["column.include.list"] + ",public.members.email"},
    )
    assert not check_connector(running, leaky).passed

    assert check_db_side("pgoutput", True, ["public.members"]).passed
    assert not check_db_side("pgoutput", False, ["public.members"]).passed
    assert not check_db_side("pgoutput", True, ["public.members", "public.members_archive"]).passed
    assert not check_db_side(None, False, []).passed
    assert params.SLOT_NAME in check_db_side(None, False, []).detail
