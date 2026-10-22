"""공통 형식 검사기(pipelines/format_rules.py) 시험. 규칙표는 docs/contracts/format_rules.yaml.

Silver는 validate()(첫 오류 하나), Gold B는 errors()(오류 전부)를 쓴다. 두 함수의 첫 오류가 같은지와,
Gold B가 기대하는 오류 목록이 나오는지를 본다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("yaml")

from pipelines.format_rules import FormatError, FormatRules  # noqa: E402

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
