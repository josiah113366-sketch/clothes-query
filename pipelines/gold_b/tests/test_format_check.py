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
from test_ddl import _utc, load_samples  # noqa: E402

UTC = timezone.utc
SAMPLES = {s["name"]: s for s in load_samples()}


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


def test_masking_keeps_business_values_only(checker):
    value = SAMPLES["multiple_errors"]["value"]
    sample = json.loads(checker(message(SAMPLES["multiple_errors"])).errors[0]["raw_sample"])
    assert set(sample) == set(value)                        # 필드 이름은 다 남는다
    for key in ("pg", "status", "method", "amount", "attempt_no", "__op"):
        assert sample[key] == value[key], key
    for key in ("payment_id", "order_id", "requested_at", "completed_at"):
        assert sample[key] == MASK, key
    member = json.loads(checker(message(SAMPLES["member_with_pii_column"])).errors[0]["raw_sample"])
    assert {member[k] for k in ("email", "member_id", "region_sigungu", "gender", "signup_at")} == {MASK}
    assert member["withdrawn_at"] is None                   # 값이 없다는 것은 보인다


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
