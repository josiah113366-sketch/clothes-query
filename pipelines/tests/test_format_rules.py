"""공통 형식 검사기(pipelines/format_rules.py) 시험. 규칙표는 docs/contracts/format_rules.yaml.

Silver는 validate()(첫 오류 하나), Gold B는 errors()(오류 전부)를 쓴다. 두 함수의 첫 오류가 같은지와,
Gold B가 기대하는 오류 목록이 나오는지를 본다.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from pipelines.format_rules import DEFAULT_RULES, FormatError, FormatRules, RuleConfigError  # noqa: E402

ORDER_ID = "00000000-4000-8000-0000-000000000009"


def payment(**changes):
    return {"payment_id": "00000000-4000-8000-0000-000000000011", "order_id": ORDER_ID, "attempt_no": 1,
            "method": "CARD", "pg": "PG_A", "amount": 11800, "status": "SUCCESS", "failure_code": None,
            "requested_at": "2026-10-21T06:00:00Z", "completed_at": "2026-10-21T06:00:02Z", **changes}


def order(**changes):
    return {"order_id": ORDER_ID, "member_id": "00000000-4000-8000-0000-000000000008",
            "session_id": "00000000-4000-8000-0000-00000000001f", "status": "PLACED", "status_reason": None,
            "total_amount": 11800, "ordered_at": "2026-10-21T06:00:00Z", "updated_at": "2026-10-21T06:00:00Z",
            **changes}


def item(**changes):
    return {"order_item_id": "00000000-4000-8000-0000-000000000004", "order_id": ORDER_ID,
            "article_id": "0108775015", "quantity": 2, "unit_price": 5900, **changes}


def found(rules, dataset, row):
    return [(error.field, error.code, error.rule_id) for error in rules.errors(dataset, row)]


@pytest.fixture(scope="module")
def rules():
    return FormatRules()


def test_valid_rows_have_no_errors(rules):
    for dataset, row in (("payments", payment()), ("orders", order()), ("order_items", item())):
        assert rules.errors(dataset, row) == []
        rules.validate(dataset, row)


def test_unit_price_minimum_is_5900(rules):
    assert found(rules, "order_items", item(unit_price=5899)) == [
        ("unit_price", "INVALID_VALUE", "order_items.fields.unit_price.minimum")]
    assert found(rules, "order_items", item(unit_price=5900)) == []


def test_errors_returns_one_error_per_field_then_checks(rules):
    # Gold B 샘플 multiple_errors와 같은 모양: 허용되지 않은 PG, 숫자로 온 시각, 실패인데 실패 코드 없음
    row = payment(pg="PG_X", status="FAILED", failure_code=None, completed_at=1792562848000)
    assert found(rules, "payments", row) == [
        ("pg", "INVALID_VALUE", "payments.fields.pg.enum"),
        ("completed_at", "TYPE_MISMATCH", "payments.fields.completed_at.type"),
        ("failure_code", "MISSING_FIELD", "payments_failed_requires_code"),
    ]


def test_checks_on_broken_fields_are_skipped(rules):
    # 상태가 틀리면 상태에 걸린 실패 코드 조건을 보지 않고, 시각을 못 읽으면 시각 비교를 하지 않는다
    assert found(rules, "payments", payment(status="DONE", completed_at="어제")) == [
        ("status", "INVALID_VALUE", "payments.fields.status.enum"),
        ("completed_at", "INVALID_VALUE", "payments.fields.completed_at.type"),
    ]


@pytest.mark.parametrize("dataset,row", [
    ("payments", payment(pg="PG_X", status="FAILED", failure_code=None, completed_at=1792562848000)),
    ("payments", payment(completed_at="2026-10-21T05:00:00Z")),   # 조건 검사만 걸림 (결과 시각이 요청보다 이름)
    ("payments", payment(failure_code="CARD_DECLINED")),           # 성공인데 실패 코드
    ("orders", order(status="CANCELLED", status_reason=None)),
    ("order_items", item(quantity=0, unit_price=100)),
])
def test_validate_raises_the_first_error(rules, dataset, row):
    first = rules.errors(dataset, row)[0]
    with pytest.raises(FormatError) as raised:
        rules.validate(dataset, row)
    assert (raised.value.field, raised.value.code, raised.value.rule_id) == (first.field, first.code, first.rule_id)


# ---------- 0.2.0: Gold B 사용 승인, 회원·클릭·리뷰, 새 규칙 종류 ----------

def member(**changes):
    return {"member_id": "00000000-4000-8000-0000-0000000000c1", "gender": "F",
            "signup_at": "2026-09-01T09:00:00+09:00", "signup_channel": "app", "marketing_consent": True,
            "status": "ACTIVE", "withdrawn_at": None, "created_at": "2026-09-01T09:00:00+09:00",
            "region_sigungu": "마포구", "age_band": "20s", **changes}


def click(**changes):
    return {"event_id": "00000000-4000-8000-0000-0000000000e1", "event_type": "view",
            "member_id": "00000000-4000-8000-0000-0000000000c1", "article_id": "0108775015",
            "event_time": "2026-10-21T15:03:09+09:00", "session_id": "00000000-4000-8000-0000-0000000000d1", **changes}


def review(**changes):
    return {"schema_version": "review.v2", "event_type": "review_created", "review_id": "r-1", "event_id": "e-1",
            "product_id": "0108775015", "text": "<본문 생략>", "rating": 4,
            "created_at": "2026-10-21T06:10:00Z", "emitted_at": "2026-10-21T06:10:01Z", **changes}


def test_both_consumers_read_the_same_rules():
    silver, gold_b = FormatRules(consumer="silver"), FormatRules(consumer="gold_b")
    assert silver.version == gold_b.version == "0.2.0"
    assert silver.digest == gold_b.digest
    assert {"members", "clickstream", "reviews"} <= set(gold_b.datasets)


def test_valid_member_click_review(rules):
    assert rules.errors("members", member()) == []
    assert rules.errors("members", member(status="WITHDRAWN", withdrawn_at="2026-10-01T00:00:00Z")) == []
    assert rules.errors("clickstream", click()) == []
    assert rules.errors("reviews", review()) == []


@pytest.mark.parametrize("dataset,row,expected", [
    ("members", member(email="<redacted>"), [("email", "INVALID_VALUE", "members.forbidden_fields.email")]),
    ("members", member(marketing_consent="true"),
     [("marketing_consent", "TYPE_MISMATCH", "members.fields.marketing_consent.type")]),
    ("members", member(age_band="80s"), [("age_band", "INVALID_VALUE", "members.fields.age_band.enum")]),
    ("members", member(withdrawn_at="2026-10-01T00:00:00Z"),
     [("withdrawn_at", "INVALID_VALUE", "members_active_not_withdrawn")]),
    # 탈퇴했는데 탈퇴 시각이 없으면 한 줄만 남는다 (같은 필드의 다음 조건은 건너뜀)
    ("members", member(status="WITHDRAWN"), [("withdrawn_at", "MISSING_FIELD", "members_withdrawn_has_time")]),
    ("members", member(status="WITHDRAWN", withdrawn_at="2026-08-01T00:00:00Z"),
     [("withdrawn_at", "INVALID_VALUE", "members_withdrawn_after_signup")]),
    ("clickstream", click(article_id="010877501"),
     [("article_id", "INVALID_VALUE", "clickstream.fields.article_id.pattern")]),
    ("clickstream", click(article_id=108775015), [("article_id", "TYPE_MISMATCH", "clickstream.fields.article_id.type")]),
    ("clickstream", click(event_type="purchase"), [("event_type", "INVALID_VALUE", "clickstream.fields.event_type.enum")]),
    ("clickstream", {key: value for key, value in click().items() if key != "session_id"},
     [("session_id", "MISSING_FIELD", "clickstream.fields.session_id.required")]),
    ("reviews", review(rating=6), [("rating", "INVALID_VALUE", "reviews.fields.rating.enum")]),
    ("reviews", review(rating=True), [("rating", "TYPE_MISMATCH", "reviews.fields.rating.type")]),
])
def test_member_click_review_errors(rules, dataset, row, expected):
    assert found(rules, dataset, row) == expected


def write_rules(tmp_path, change):
    document = yaml.safe_load(DEFAULT_RULES.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("change", [
    lambda d: d["source_rules"]["orders"]["fields"]["total_amount"].update(pattern="[0-9]+"),   # pattern은 문자열만
    lambda d: d["source_rules"]["clickstream"]["fields"]["article_id"].update(pattern="[0-9"),    # 잘못된 정규식
    lambda d: d["source_rules"]["members"]["fields"]["marketing_consent"].update(enum=[True]),    # 참/거짓에 허용 목록 없음
    lambda d: d["source_rules"]["members"].update(forbidden_fields=["member_id"]),                # 있어야 할 필드를 금지
    lambda d: d["source_rules"]["members"].update(source={"revision": "abc"}),                    # 원천 경로 없음
])
def test_bad_rule_definitions_stop_loading(tmp_path, change):
    with pytest.raises(RuleConfigError):
        FormatRules(write_rules(tmp_path, change), consumer="gold_b")
