"""Partial results never become operating publication or invented healthy data."""
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import pytest

from gold_a_evidence import FunnelEvidence
from gold_a_io import GoldAError, GoldAReader
from test_gold_a_io import Athena, TODAY

ROOT = "s3://test-lake"
RUN = "funnels-ack"


class S3:
    def __init__(self):
        self.objects = {}
        inv = {"objects": [{"uri": ROOT + f"/bronze_v2/clickstream/{i}", "etag": str(i), "size": 10}
                           for i in range(3)]}
        inventory = self.add("pipelines/input-manifests/inventory.json", inv)
        self.manifest = {"run_id": RUN, "status": "PARTIAL", "version": "funnel-incremental.v1",
                         "checked_at": "2026-10-24T10:00:00+09:00", "inventory": inventory,
                         "processed": [[o['uri'], o['etag'], o['size']] for o in inv['objects'][:2]],
                         "batch": {"remaining_files": 1}, "coverage_status": "BACKFILL_IN_PROGRESS",
                         "output_counts": {"funnel_daily": 1, "funnel_session_product": 1, "refresh_holds": 1},
                         "held_scopes": [{"reason": "BACKFILL_IN_PROGRESS"}],
                         "outputs": {n: ROOT + f"/gold_a/runtime/funnels/runs/{RUN}/{n}" for n in
                                     ("funnel_daily", "funnel_session_product", "refresh_holds")}}
        self.save()

    def add(self, key, doc):
        raw = json.dumps(doc, sort_keys=True).encode()
        self.objects[key] = raw
        return {"uri": ROOT + "/" + key, "sha256": hashlib.sha256(raw).hexdigest()}

    def save(self):
        ref = self.add(f"gold_a/runtime/funnels/runs/{RUN}/manifest.json", self.manifest)
        self.add(f"gold_a/runtime/funnels/completed/{RUN}.json", self.manifest)
        self.add("silver/runtime/clicks/catalog-control/incremental.json",
                 {"tip": ref, "owner": "new-unfinished-run", "athena_query_id": "verified-query"})

    def get_object(self, Bucket, Key):
        assert Bucket == "test-lake"
        return {"Body": io.BytesIO(self.objects[Key])}


class DemoAthena(Athena):
    def result(self, sql):
        if " AS metric, count(*) AS n" in sql:
            return ["metric", "n"], [[n, "1"] for n in ("funnel_daily", "funnel_session_product", "refresh_holds")]
        columns, rows = super().result(sql)
        if ".gold_runs " in sql and "channel = 'reviews'" in sql and rows:
            rows[0][2], rows[0][3] = "PASS", "0"
        return columns, rows


def demo_reader(s3=None, client=None):
    return GoldAReader(client or DemoAthena(partial=True), "test", today=TODAY,
                       mode="demo", funnel_evidence=FunnelEvidence(s3 or S3(), ROOT))


def test_acknowledged_tip_scope_and_actual_athena_counts():
    r = demo_reader()
    m = r.run("funnels")
    assert m["run_id"] == RUN and m["quality_status"] == "PARTIAL"
    assert m["scope"] == "처리 2/3파일 · 미처리 1파일"
    assert r.read("funnel_daily").attrs["run_id"] == RUN
    assert len(r.holds("funnels")) == 1
    assert all(RUN in s for s in r.client.sql)


@pytest.mark.parametrize("kind", ["sha", "done", "scope", "duplicate", "counts", "path", "status", "permission"])
def test_unverified_evidence_is_blocked(kind):
    s = S3()
    if kind == "sha":
        s.objects[f"gold_a/runtime/funnels/runs/{RUN}/manifest.json"] += b" "
    elif kind == "done":
        s.add(f"gold_a/runtime/funnels/completed/{RUN}.json", {})
    elif kind == "permission":
        s.get_object = lambda **kw: (_ for _ in ()).throw(PermissionError())
    else:
        if kind == "scope": s.manifest["batch"]["remaining_files"] = 0
        if kind == "duplicate": s.manifest["processed"] *= 2
        if kind == "counts": s.manifest["output_counts"]["funnel_daily"] = 2
        if kind == "path": s.manifest["outputs"]["funnel_daily"] = ROOT + "/wrong"
        if kind == "status": s.manifest["status"] = "PASS"
        s.save()
    with pytest.raises(GoldAError):
        demo_reader(s).run("funnels")


def test_operation_does_not_read_checkpoint_or_select_demo_run():
    r = GoldAReader(Athena(no_run=True), "test", mode="operation", selected_runs={"trade": "demo"})
    assert r.run("funnels") is None
    assert "run_id = 'demo'" not in r.client.sql[0]


def test_trade_selection_and_reviews_unchanged():
    r = GoldAReader(DemoAthena(partial=True), "test", mode="demo", selected_runs={"trade": "run-a"})
    assert r.run("trade")["quality_status"] == "PARTIAL"
    assert "AND run_id = 'run-a'" in r.client.sql[0]
    assert r.read("review_product_daily").attrs['run_id'] == 'run-a'
    assert "AND run_id = 'run-a'" not in [s for s in r.client.sql if "channel = 'reviews'" in s][0]


def test_real_status_and_unconfigured_gold_b_reliability_are_distinguished(monkeypatch):
    import data
    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    r = demo_reader()
    monkeypatch.setattr(data, "gold_reader", lambda: r)
    df = data.get_data_status()
    assert "미검증" in df.processed_until_kst.iloc[0]
    # 최신 main의 신뢰성 검사는 Gold B 연결이다. 미설정 fixture의 더미를 실데이터로 오인하지 않는다.
    monkeypatch.delitem(data._REAL, "get_reliability_checks", raising=False)
    checks = data.get_reliability_checks()
    assert not checks.empty
    assert "get_data_status" not in data.USING_DUMMY
    assert "get_reliability_checks" in data.USING_DUMMY


@pytest.mark.parametrize("page", ["funnel", "orders", "reviews"])
def test_actual_page_modes_and_partial_warning(monkeypatch, page):
    from streamlit.testing.v1 import AppTest
    import auth
    import data
    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setattr(auth, "require_role", lambda *a: None)
    r = demo_reader()
    r.run_options = lambda *a: pd.DataFrame([{"run_id": "run-a", "quality_status": "PARTIAL"}])
    monkeypatch.setattr(data, "gold_reader", lambda: r)
    at = AppTest.from_file(str(Path(__file__).parent / 'pages_product' / (page + '.py')), default_timeout=30).run()
    at.radio[0].set_value("시연·검증").run()
    assert not at.exception and not at.error
    assert any("시연·검증 모드" in v.value for v in at.warning)
    assert any("부분 데이터" in v.value for v in at.warning) == (page != "reviews")
    if page == "funnel":
        assert any("처리 2/3파일" in c.value for c in at.caption)
    if page == "reviews":
        at.slider[0].set_value(3).run()
        assert not at.exception and not at.error
        assert any("PASS" in c.value for c in at.caption)
        at.multiselect[0].set_value([]).run()
        assert not at.exception and any("하나 이상" in v.value for v in at.info)


def test_operation_reads_acknowledged_partial_only_when_registry_is_empty():
    client = DemoAthena(no_run=True, partial=True)
    r = GoldAReader(client, "test", today=TODAY, mode="operation",
                    funnel_evidence=FunnelEvidence(S3(), ROOT))
    row = r.run("funnels")
    assert row["run_id"] == RUN and row["quality_status"] == "PARTIAL"
    assert row["coverage_status"] == "BACKFILL_IN_PROGRESS"
    assert row["partial_publication"] is True and row["demo_only"] is False
    assert row["scope"] == "처리 2/3파일 · 미처리 1파일"
    assert r.read("funnel_daily").attrs["run_id"] == RUN
    assert len(r.holds("funnels")) == 1
    assert all(sql.lstrip().startswith("SELECT") for sql in client.sql)
    assert any(".gold_runs " in sql for sql in client.sql)


def test_operation_prefers_formally_completed_funnel_over_partial_tip():
    class UnexpectedEvidence:
        def latest(self):
            raise AssertionError("공개 완료 실행이 있으면 부분 checkpoint를 읽지 않는다")
    r = GoldAReader(Athena(), "test", today=TODAY, mode="operation", funnel_evidence=UnexpectedEvidence())
    assert r.run("funnels")["run_id"] == "run-a"
    assert r.run("funnels")["quality_status"] == "PASS"


def test_operation_never_promotes_unpublished_pass_manifest():
    class CompletedEvidence:
        def latest(self):
            row = FunnelEvidence(S3(), ROOT).latest()
            row.update(quality_status="PASS", coverage_status="COMPLETE")
            return row
    r = GoldAReader(DemoAthena(no_run=True), "test", mode="operation", funnel_evidence=CompletedEvidence())
    with pytest.raises(GoldAError, match="정식 공개"):
        r.run("funnels")


def test_operation_partial_does_not_bypass_missing_s3_permissions():
    s3 = S3()
    s3.get_object = lambda **kw: (_ for _ in ()).throw(PermissionError())
    r = GoldAReader(DemoAthena(no_run=True), "test", mode="operation", funnel_evidence=FunnelEvidence(s3, ROOT))
    with pytest.raises(GoldAError, match="읽지 못했습니다"):
        r.run("funnels")


def test_operation_partial_funnel_daily_uses_bounded_expanded_limit():
    class MoreRows(DemoAthena):
        def result(self, sql):
            columns, rows = super().result(sql)
            if "FROM gold_a.funnel_daily_runs" in sql and "SELECT DISTINCT" not in sql and " AS metric" not in sql:
                rows = rows * 3
            return columns, rows
    r = GoldAReader(MoreRows(no_run=True, partial=True), "test", today=TODAY, mode="operation", max_rows=2,
                    funnel_evidence=FunnelEvidence(S3(), ROOT))
    # checkpoint count 검증은 3행이므로 일반 한도 3으로 설정하고 일별 4행을 조회한다.
    r.max_rows = 3
    original = r.client.result
    def result(sql):
        columns, rows = original(sql)
        if "FROM gold_a.funnel_daily_runs" in sql and "SELECT DISTINCT" not in sql and " AS metric" not in sql:
            rows = rows + rows[:1]
        return columns, rows
    r.client.result = result
    assert len(r.read("funnel_daily")) == 4


def test_operation_partial_page_shows_scope_and_backfill_warning(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import auth
    import data
    monkeypatch.setenv("GOLD_A_DATA_SOURCE", "athena")
    monkeypatch.setattr(auth, "require_role", lambda *a: None)
    r = GoldAReader(DemoAthena(no_run=True, partial=True), "test", today=TODAY,
                    mode="operation", funnel_evidence=FunnelEvidence(S3(), ROOT))
    monkeypatch.setattr(data, "gold_reader", lambda: r)
    at = AppTest.from_file(str(Path(__file__).parent / "pages_product/funnel.py"), default_timeout=30)
    at.session_state["_gold_a_mode"] = "operation"
    at.run()
    assert not at.exception and not at.error
    assert at.radio[0].value == "운영"
    assert any("PARTIAL / 백필 진행 중" in w.value for w in at.warning)
    assert any("처리 2/3파일" in c.value for c in at.caption)
    assert any(RUN in c.value for c in at.caption)
    assert any("세션" in k.value for k in at.markdown)
