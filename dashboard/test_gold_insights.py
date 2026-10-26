"""동일 실행·코호트의 경로 비교 및 필터된 속성 건수 회귀."""
import pytest
from streamlit.testing.v1 import AppTest
from pathlib import Path

from gold_a_io import GoldAError
from test_gold_a_io import Athena, reader

EXPECTED = dict(view_sessions=410319, cart_sessions=29501, order_sessions=12916,
                paid_sessions=12117, cart_order_sessions=12068)


class PathsAthena(Athena):
    def __init__(self, **overrides):
        super().__init__()
        self.values = dict(EXPECTED, order_without_cart=848, order_with_cart=12068, invalid_rows=0)
        self.values.update(overrides)

    def result(self, sql):
        if " AS order_without_cart" in sql:
            return list(self.values), [[str(v) for v in self.values.values()]]
        if "SELECT DISTINCT" in sql:
            return ["article_id", "product_code"], [["p1", "1"], ["p2", "2"]]
        return super().result(sql)


def test_actual_observed_counts_and_same_cohort_sql():
    client = PathsAthena()
    result = reader(client).funnel_order_paths(14, ["p1", "p2"], EXPECTED)
    assert f"{result['without_cart_rate']:.2%}" == "6.57%"
    assert result["order_without_cart"] == 848
    sql = client.sql[-1]
    assert "has_order AND NOT has_cart" in sql
    assert "run_id = 'run-a'" in sql and "first_view_at_kst" in sql
    assert "BETWEEN DATE '2026-10-11' AND DATE '2026-10-24'" in sql
    assert "article_id IN" not in sql and "LIMIT" not in sql


def test_subset_is_filtered_and_cart_after_order_is_not_missing_cart():
    client = PathsAthena(order_without_cart=800, order_with_cart=12116)
    result = reader(client).funnel_order_paths(14, ["p1"], EXPECTED)
    assert result["order_without_cart"] == 800  # not orders - ordered_after_cart (=848)
    assert "article_id IN ('p1')" in client.sql[-1]


@pytest.mark.parametrize("overrides,expected", [
    ({"invalid_rows": 1}, EXPECTED),
    ({"order_without_cart": 849}, EXPECTED),
    ({}, dict(EXPECTED, view_sessions=1)),
    ({"order_sessions": 0, "order_without_cart": 0, "order_with_cart": 0}, dict(EXPECTED, order_sessions=0)),
])
def test_incomparable_counts_are_unavailable(overrides, expected):
    with pytest.raises(GoldAError, match="분석 불가"):
        reader(PathsAthena(**overrides)).funnel_order_paths(14, ["p1"], expected)


def test_unknown_or_no_selected_product_is_unavailable():
    for products in [[], ["unknown"]]:
        with pytest.raises(GoldAError, match="분석 불가"):
            reader(PathsAthena()).funnel_order_paths(14, products, EXPECTED)


def test_review_rate_and_count_table_use_actual_filtered_gold(monkeypatch):
    import auth
    import data
    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setattr(auth, "require_role", lambda *a: None)
    r = reader()
    monkeypatch.setattr(data, "gold_reader", lambda: r)
    at = AppTest.from_file(str(Path(__file__).parent / "pages_product/reviews.py"), default_timeout=30).run()
    assert not at.exception and not at.error
    table = next(x.value for x in at.dataframe if "부정 건수" in x.value.columns)
    assert table.iloc[0]["부정 건수"] == 3
    assert table.iloc[0]["분석 점수 건수"] == 10
    assert table.iloc[0]["부정 비율"] == pytest.approx(.3)
    assert "s2c · 1.0" in at.selectbox[0].options
