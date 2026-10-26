"""AWS 호출 없이 실제 Athena 응답 형식과 Streamlit 화면 경로를 검증한다."""

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gold_a_io import HOLD_COLUMNS, TABLES, GoldAError, GoldAReader

TODAY = date(2026, 10, 24)


class Athena:
    def __init__(self, no_run=False, partial=False, empty=False, failed=False):
        self.sql = []
        self.no_run, self.partial, self.empty, self.failed = no_run, partial, empty, failed
        self.cancelled = []

    def start_query_execution(self, **kwargs):
        self.sql.append(kwargs["QueryString"])
        return {"QueryExecutionId": str(len(self.sql) - 1)}

    def get_query_execution(self, **kwargs):
        return {"QueryExecution": {"Status": {"State": "FAILED" if self.failed else "SUCCEEDED"}}}

    def stop_query_execution(self, QueryExecutionId):
        self.cancelled.append(QueryExecutionId)

    def get_paginator(self, name):
        assert name == "get_query_results"
        return self

    def result(self, sql):
        if " AS order_without_cart" in sql:
            return ["view_sessions", "cart_sessions", "order_sessions", "paid_sessions",
                    "cart_order_sessions", "order_without_cart", "order_with_cart", "invalid_rows"], [["1", "1", "1", "1", "1", "0", "1", "0"]]
        if ".gold_runs " in sql:
            columns = [
                "run_id",
                "completed_at",
                "quality_status",
                "held_scope_count",
                "available_tables_json",
            ]
            channel = re.search("channel = '([^']+)'", sql)[1]
            tables = {k: 1 for k, v in TABLES.items() if v[0] == channel}
            if channel != "reviews":
                tables["refresh_holds"] = int(self.partial)
            rows = (
                []
                if self.no_run
                else [
                    [
                        "run-a",
                        "2026-10-24 02:00:00.123",
                        "PARTIAL" if self.partial else "PASS",
                        str(int(self.partial)),
                        json.dumps(tables),
                    ]
                ]
            )
            return columns, rows
        if ".refresh_holds_runs " in sql:
            rows = (
                [
                    [
                        "product_sales_daily",
                        '{"sales_date_kst":"2026-10-24","article_id":"0000000001"}',
                        "ORDER_AMOUNT_MISMATCH",
                        "false",
                        None,
                    ]
                ]
                if self.partial
                else []
            )
            return HOLD_COLUMNS, rows
        if "SELECT DISTINCT" in sql:
            return ["article_id", "product_code"], [["0000000001", "1"]]
        table = re.search(r"FROM gold_a\.(\w+)_runs", sql)[1]
        columns = TABLES[table][2].split()
        values = {
            "article_id": "0000000001",
            "product_code": "1",
            "session_id": "session-1",
            "aspect": "색상·디자인",
            "model_version": "s2c",
            "model_version_no": "1.0",
        }
        for c in columns:
            if c.endswith("_kst"):
                values[c] = (
                    "2026-10-24T09:00:00.123456+09:00"
                    if "at_kst" in c or c == "hour_start_kst"
                    else "2026-10-24"
                )
            elif c.startswith("has_") or c == "ordered_after_cart":
                values[c] = "true"
            elif c not in values:
                values[c] = "1"
        if table == "review_aspect_daily":
            values.update(
                scored_review_count="10",
                score_neg2_count="2",
                score_neg1_count="1",
                score_zero_count="3",
                score_pos1_count="2",
                score_pos2_count="2",
            )
        return columns, [] if self.empty else [[values[c] for c in columns]]

    def paginate(self, QueryExecutionId):
        columns, rows = self.result(self.sql[int(QueryExecutionId)])
        metadata = {"ColumnInfo": [{"Name": c} for c in columns]}

        def cells(row):
            return {"Data": [{} if v is None else {"VarCharValue": v} for v in row]}

        # Header and data on separate pages exercises pagination and NULL preservation.
        yield {"ResultSet": {"ResultSetMetadata": metadata, "Rows": [cells(columns)]}}
        yield {"ResultSet": {"ResultSetMetadata": metadata, "Rows": [cells(r) for r in rows]}}


def reader(client=None, **kwargs):
    return GoldAReader(client or Athena(), "test-workgroup", today=TODAY, **kwargs)


def test_pins_registry_and_holds_to_one_run():
    client = Athena(partial=True)
    r = reader(client)
    assert r.read("order_sales_hourly").iloc[0].approved_amount == 1
    assert r.read("product_sales_daily").iloc[0].sold_quantity == 1
    assert len([q for q in client.sql if ".gold_runs " in q]) == 1
    assert all("run_id = 'run-a'" in q for q in client.sql if ".gold_runs " not in q)
    assert r.holds("trade").iloc[0].previous_result_available == False


def test_review_counts_and_version_are_actual_gold_schema():
    df = reader().read("review_aspect_daily")
    assert df.iloc[0].mentioned_review_count == 10
    assert df.iloc[0].negative_review_count == 3
    assert df.iloc[0].positive_review_count == 4
    assert df.iloc[0].negative_rate == 0.3
    assert df.iloc[0].model_key == "s2c · 1.0"
    assert str(df.iloc[0].review_date_kst.date()) == "2026-10-24"


def test_kst_microseconds_and_detail_boolean():
    df = reader().read("order_sales_hourly")
    assert df.iloc[0].hour_start_kst == pd.Timestamp("2026-10-24 09:00:00.123456")
    detail = reader().read("funnel_session_product", article_id="0000000001")
    assert bool(detail.iloc[0].has_view)


@pytest.mark.parametrize("no_run,empty,state", [(True, False, "NO_RUN"), (False, True, "OK")])
def test_empty_is_not_dummy_or_zero(no_run, empty, state):
    df = reader(Athena(no_run=no_run, empty=empty)).read("product_sales_daily")
    assert df.empty and df.attrs["state"] == state


def test_failure_and_timeout_stop_instead_of_returning_dummy():
    client = Athena(failed=True)
    with pytest.raises(GoldAError):
        reader(client).read("order_sales_hourly")
    assert client.cancelled
    client.get_query_execution = lambda **kw: {"QueryExecution": {"Status": {"State": "RUNNING"}}}
    with pytest.raises(GoldAError, match="초과"):
        reader(client, timeout=0).read("order_sales_hourly")


def test_mismatched_holds_block_metrics():
    client = Athena(partial=True)
    original = client.result
    client.result = lambda sql: (
        (HOLD_COLUMNS, []) if ".refresh_holds_runs " in sql else original(sql)
    )
    with pytest.raises(GoldAError, match="공개 건수"):
        reader(client).read("product_sales_daily")


def test_products_are_real_ids_and_cached():
    client = Athena()
    r = reader(client)
    assert list(r.products(("trade",)).article_id) == ["0000000001"]
    r.products(("trade",))
    assert len([q for q in client.sql if "SELECT DISTINCT" in q]) == 1


@pytest.mark.parametrize("name", ["orders", "product_sales", "funnel", "reviews", "overview"])
def test_real_pages(monkeypatch, name):
    from streamlit.testing.v1 import AppTest

    import auth
    import data

    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setattr(auth, "require_role", lambda *args: None)
    monkeypatch.setattr(data, "gold_reader", lambda: real_reader)
    real_reader = reader()
    at = AppTest.from_file(
        str(Path(__file__).parent / "pages_product" / f"{name}.py"), default_timeout=30
    ).run()
    assert not at.exception
    assert not at.error
    assert any("run-a" in c.value for c in at.caption)
    if name != "orders":
        widgets = at.multiselect or at.selectbox
        assert "0000000001" in str(widgets[0].options)


@pytest.mark.parametrize("kind", ["no_run", "empty", "failed", "partial"])
def test_page_reports_real_state(monkeypatch, kind):
    from streamlit.testing.v1 import AppTest

    import auth
    import data

    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setattr(auth, "require_role", lambda *args: None)
    real_reader = reader(Athena(**{kind: True}))
    monkeypatch.setattr(data, "gold_reader", lambda: real_reader)
    at = AppTest.from_file(
        str(Path(__file__).parent / "pages_product/orders.py"), default_timeout=30
    ).run()
    assert not at.exception
    if kind == "failed":
        assert at.error and not at.metric
    elif kind == "partial":
        assert at.warning and at.dataframe
    else:
        assert at.info and not at.metric


def test_page_refresh_selects_new_run_without_shared_cache(monkeypatch):
    import boto3
    from streamlit.testing.v1 import AppTest

    import auth
    import data

    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setenv("GOLD_A_ATHENA_WORKGROUP", "test-workgroup")
    monkeypatch.setattr(auth, "require_role", lambda *args: None)
    client = Athena()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    at = AppTest.from_file(
        str(Path(__file__).parent / "pages_product/orders.py"), default_timeout=30
    ).run()
    assert not at.exception and not at.error
    assert any("run-a" in c.value for c in at.caption)
    original = client.result

    def new_run(sql):
        columns, rows = original(sql)
        if ".gold_runs " in sql:
            rows[0][0] = "run-b"
        return columns, rows

    client.result = new_run
    at.run()
    assert not at.exception and not at.error
    assert any("run-b" in c.value for c in at.caption)
    assert len([q for q in client.sql if ".gold_runs " in q]) == 2
    assert "run_id = 'run-b'" in client.sql[-1]
    assert "get_order_sales_hourly" not in data.USING_DUMMY


def test_review_page_does_not_merge_model_numbers(monkeypatch):
    from streamlit.testing.v1 import AppTest

    import auth
    import data

    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setattr(auth, "require_role", lambda *args: None)
    client = Athena()
    original = client.result

    def two_models(sql):
        columns, rows = original(sql)
        if ".review_aspect_daily_runs " in sql:
            second = list(rows[0])
            second[columns.index("model_version_no")] = "2.0"
            second[columns.index("scored_review_count")] = "20"
            rows.append(second)
        return columns, rows

    client.result = two_models
    real_reader = reader(client)
    monkeypatch.setattr(data, "gold_reader", lambda: real_reader)
    at = AppTest.from_file(
        str(Path(__file__).parent / "pages_product/reviews.py"), default_timeout=30
    ).run()
    assert not at.exception and not at.error
    assert list(at.selectbox[0].options) == ["s2c · 1.0", "s2c · 2.0"]
    assert at.dataframe[0].value["분석 점수 건수"].sum() == 10
    at.selectbox[0].select("s2c · 2.0").run()
    assert not at.exception and not at.error
    assert at.dataframe[0].value["분석 점수 건수"].sum() == 20


def test_trade_query_limit_does_not_change_review_or_generic_query_limit():
    class MoreRows(Athena):
        def result(self, sql):
            columns, rows = super().result(sql)
            if "SELECT DISTINCT" not in sql and any(name in sql for name in (
                    ".product_sales_daily_runs", ".review_product_daily_runs")):
                rows = rows * 3
            return columns, rows

    r = reader(MoreRows(), max_rows=2)
    assert len(r.read("product_sales_daily", days=3)) == 3
    with pytest.raises(GoldAError, match="한도"):
        r.read("review_product_daily", days=3)
    with pytest.raises(GoldAError, match="한도"):
        r.query("SELECT article_id FROM gold_a.product_sales_daily_runs")
