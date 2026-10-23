"""형식 검사기 시험. 샘플 메시지(samples/)의 기대 결과와 같은지, 결제 줄·지문·마스킹을 확인한다.

규칙표는 저장소의 docs/contracts/format_rules.yaml(소비 경로 gold_b)이다. Kafka·S3에는 붙지 않는다.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("pyarrow")

from pipelines.format_rules import DEFAULT_RULES, FormatRules, RuleConfigError  # noqa: E402
from pipelines.gold_b.format_check import DATASETS, MASK, FormatChecker, mask_sample  # noqa: E402
from pipelines.gold_b.ledger import PAYMENT_FIELDS, KafkaMessage, message_rows  # noqa: E402
from pipelines.payment_fingerprint import payment_fingerprint  # noqa: E402
from pipelines.timestamps import parse_iso_datetime  # noqa: E402
from test_ddl import _utc, load_payment_updates, load_samples  # noqa: E402

UTC = timezone.utc
SAMPLES = {s["name"]: s for s in load_samples() + load_payment_updates()}


@pytest.fixture(scope="module")
def checker():
    return FormatChecker()


def message(sample: dict) -> KafkaMessage:
    k = sample["kafka"]
    raw = sample["value_raw"] if "value_raw" in sample else json.dumps(sample["value"], ensure_ascii=False)
    return KafkaMessage(k["topic"], k["partition"], k["offset"], _utc(k["timestamp"]), raw.encode("utf-8"))


def raw_message(topic: str, value: bytes | None) -> KafkaMessage:
    return KafkaMessage(topic, 0, 1, datetime(2026, 10, 21, 6, 0, tzinfo=UTC), value)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_sample_matches_expected(checker, name):
    sample = SAMPLES[name]
    judgement = checker(message(sample))
    expected = sample["expected"]
    assert (judgement.payment is not None) == expected["payment_events"]
    # 오류 순서는 검사기 순서(필드 → 금지 필드 → 조건)라 샘플과 다를 수 있어 묶음으로 비교한다
    assert Counter((e["field"], e["reason"]) for e in judgement.errors) == \
        Counter((e["field"], e["reason"]) for e in expected["malformed"])
    assert all(e["raw_sample"] is None for e in judgement.errors[1:])   # raw_sample은 첫 줄에만


def test_payment_row_has_fingerprint_and_completed_at(checker):
    sample = SAMPLES["success_pg_a"]
    payment = checker(message(sample)).payment
    assert set(payment) == set(PAYMENT_FIELDS)
    value = sample["value"]
    assert payment["completed_at"] == parse_iso_datetime(value["completed_at"])
    assert payment["completed_at"].utcoffset() is not None   # 시간대가 있어서 message_rows가 UTC로 바꾼다
    assert {k: payment[k] for k in ("payment_content_hash", "fingerprint_version")} == payment_fingerprint(value)
    duplicate = checker(message(SAMPLES["duplicate_of_success_pg_a"])).payment
    assert duplicate["payment_content_hash"] == payment["payment_content_hash"]
    first, second = (checker(message(SAMPLES[n])).payment for n in ("conflict_amount_first", "conflict_amount_second"))
    assert first["payment_content_hash"] != second["payment_content_hash"]   # 금액만 달라도 지문이 다르다


@pytest.mark.parametrize("text, expected", [
    ("2026-10-21T06:01:00Z", datetime(2026, 10, 21, 6, 1, 0, tzinfo=UTC)),
    ("2026-10-21T06:01:00.5Z", datetime(2026, 10, 21, 6, 1, 0, 500000, tzinfo=UTC)),
    ("2026-10-21T15:01:00.5+09:00", datetime(2026, 10, 21, 6, 1, 0, 500000, tzinfo=UTC)),
])
def test_payment_completed_at_uses_the_shared_parser(checker, text, expected):
    """결제 시각은 공통 파서로 읽는다. 팀 Spark 이미지의 Python 3.10에서 datetime.fromisoformat이 못 읽는
    Z·1자리 소수초도 같은 순간이 된다."""
    sample = SAMPLES["success_pg_a"]
    payment = checker(message({**sample, "value": {**sample["value"], "completed_at": text}})).payment
    assert payment is not None and payment["completed_at"] == expected


class NoErrorRules:
    """모든 행을 통과시키는 가짜 규칙표. 규칙표가 통과시킨 결제의 지문 오류 처리만 보려고 쓴다."""

    version = "test"
    datasets = {name: {} for name in DATASETS.values()}

    def errors(self, dataset, row):
        return []


def test_fingerprint_error_becomes_invalid_value():
    value = {**SAMPLES["success_pg_a"]["value"], "completed_at": "2026-10-21T06:00:02.1234567Z"}   # 소수초 7자리
    judgement = FormatChecker(NoErrorRules())(raw_message("payments", json.dumps(value).encode("utf-8")))
    assert judgement.payment is None
    assert [(e["field"], e["reason"]) for e in judgement.errors] == [("completed_at", "INVALID_VALUE")]


def raw_sample_of(checker, name: str) -> dict:
    return json.loads(checker(message(SAMPLES[name])).errors[0]["raw_sample"])


def test_masking_shows_business_values_ids_and_times(checker):
    """raw_sample: 업무 값과 결제·주문 ID, 시각은 보이고 회원 정보는 가린다 (2026-10-23 결정)."""
    value = SAMPLES["multiple_errors"]["value"]
    sample = raw_sample_of(checker, "multiple_errors")
    assert set(sample) == set(value)                        # 필드 이름은 다 남는다
    for key in ("pg", "status", "method", "amount", "attempt_no", "__op", "__source_ts_ms",
                "payment_id", "order_id", "requested_at", "completed_at"):
        assert sample[key] == value[key], key
    order, order_value = raw_sample_of(checker, "order_bad_status"), SAMPLES["order_bad_status"]["value"]
    for key in ("order_id", "ordered_at", "updated_at", "status"):
        assert order[key] == order_value[key], key
    assert order["member_id"] == order["session_id"] == MASK
    click = raw_sample_of(checker, "click_bad_event_type")
    assert click["event_time"] == SAMPLES["click_bad_event_type"]["value"]["event_time"]
    assert {click[k] for k in ("event_id", "member_id", "session_id", "article_id")} == {MASK}
    member = raw_sample_of(checker, "member_with_pii_column")
    assert {member[k] for k in ("email", "member_id", "region_sigungu", "gender", "signup_at",
                                "__source_ts_ms")} == {MASK}
    assert member["withdrawn_at"] is None                   # 값이 없다는 것은 보인다


def test_payment_update_is_a_payment_event(checker):
    """결제 u도 ① 줄이 된다. 변경 종류와 원본 변경 시각을 남긴다 (2026-10-23)."""
    for name, op in (("success_pg_a", "c"), ("duplicate_of_success_pg_a", "r"), ("update_op", "u")):
        payment = checker(message(SAMPLES[name])).payment
        assert payment is not None, name
        assert (payment["cdc_op"], payment["source_ts_ms"]) == (op, SAMPLES[name]["value"]["__source_ts_ms"])


@pytest.mark.parametrize("source_ts, reason", [
    (None, "MISSING_FIELD"), ("1792562460500", "TYPE_MISMATCH"), (True, "TYPE_MISMATCH"), (-1, "INVALID_VALUE"),
])
def test_payment_needs_source_ts_ms(checker, source_ts, reason):
    """결제 CDC 줄은 변경 시각이 0 이상의 정수여야 한다 (Silver 거래 검사와 같은 오류 코드). 오류 줄에도 키가 남는다."""
    value = {**SAMPLES["update_op"]["value"]}
    if source_ts is None:
        del value["__source_ts_ms"]
    else:
        value["__source_ts_ms"] = source_ts
    judgement = checker(raw_message("payments", json.dumps(value).encode("utf-8")))
    assert judgement.payment is None
    assert [(e["field"], e["reason"], e["record_key"], e["source_ts_ms"]) for e in judgement.errors] == \
        [("__source_ts_ms", reason, value["payment_id"], None)]


def test_error_rows_keep_record_key_and_source_ts(checker):
    """오류 줄마다 메시지의 키와 변경 시각을 남긴다. 회원은 키를 남기지 않고, 읽지 못한 메시지는 둘 다 비어 있다."""
    keys = {"payments": "payment_id", "orders": "order_id", "order-items": "order_item_id", "clickstream": "event_id"}
    with_source_ts = {"payments", "orders", "order-items"}
    checked = 0
    for sample in SAMPLES.values():
        if not sample["expected"]["malformed"]:
            continue
        topic, value = sample["kafka"]["topic"], sample.get("value")
        value = value if isinstance(value, dict) else {}
        key = value.get(keys[topic]) if topic in keys else None
        source_ts = value.get("__source_ts_ms") if topic in with_source_ts else None
        if type(source_ts) is not int or source_ts < 0:   # 0 이상의 정수가 아니면 비운다
            source_ts = None
        for error in checker(message(sample)).errors:
            assert (error["record_key"], error["source_ts_ms"]) == (key, source_ts), sample["name"]
        checked += 1
    assert checked >= 10
    assert checker(message(SAMPLES["member_with_pii_column"])).errors[0]["record_key"] is None
    assert checker(message(SAMPLES["parse_error"])).errors[0]["record_key"] is None


def test_mask_sample_hides_long_values_and_limits_length():
    assert json.loads(mask_sample("payments", {"pg": "x" * 41, "status": "FAILED", "note": "y"})) == \
        {"pg": MASK, "status": "FAILED", "note": MASK}
    assert len(mask_sample("payments", {f"field_{i}": i for i in range(500)})) <= 1000


def test_topics_without_rules_are_not_checked(checker):
    for topic in ("reviews.raw", "other-topic"):
        judgement = checker(raw_message(topic, b"not json"))
        assert judgement.payment is None and not judgement.errors


@pytest.mark.parametrize("value", [None, b"\xff\xfe", b"[1, 2]", b'"text"', b'{"order_id": '])
def test_unreadable_values_are_parse_errors(checker, value):
    judgement = checker(raw_message("orders", value))
    assert [(e["field"], e["reason"], e["raw_sample"]) for e in judgement.errors] == \
        [("__message__", "PARSE_ERROR", None)]


def test_rule_version_and_missing_rules(tmp_path):
    assert FormatChecker().rule_version == FormatRules(consumer="gold_b").version
    document = yaml.safe_load(DEFAULT_RULES.read_text(encoding="utf-8"))
    del document["source_rules"]["clickstream"]
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(RuleConfigError):   # Gold B가 쓰는 규칙이 없으면 만들 때 실패한다
        FormatChecker(rules_path=path)


def test_all_samples_through_message_rows(checker):
    """검사 결과에 위치·적재 시각·규칙 버전을 붙여 원장 줄이 되는지 (적재 잡·재처리 잡과 같은 길)."""
    loaded_at = datetime(2026, 10, 21, 7, 0)
    totals: Counter = Counter()
    for sample in SAMPLES.values():
        rows = message_rows(message(sample), checker(message(sample)), checker.rule_version, loaded_at)
        totals.update({table: len(items) for table, items in rows.items()})
        assert all(row["rule_version"] == checker.rule_version for row in rows["malformed_events"])
    assert totals["topic_messages"] == len(SAMPLES)
    assert totals["payment_events"] == sum(s["expected"]["payment_events"] for s in SAMPLES.values())
    assert totals["malformed_events"] == sum(len({e["field"] for e in s["expected"]["malformed"]})
                                             for s in SAMPLES.values())
