"""감성분석 모델 화면의 실데이터 조회(model_io.py) 시험. 가짜 Athena·S3 를 써서 AWS 없이 돈다.
실행(저장소 루트에서): python -m pytest dashboard/test_model_io.py -q
확인하는 것: review_date 조건, 더미 대체 없음(실패는 ModelDataUnavailable), 후기 원문은 review_id 몇 건에 한해서만 읽음, 잘못된 입력 거부.
"""

import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import model_io

CFG = model_io.Config(
    staging_uri="s3://b/staging/review-score/", silver_root_uri="s3://b/silver/runtime/reviews/"
)
TODAY = pd.Timestamp("2026-10-25")


class FakeS3:
    def __init__(self, objects):
        self.objects = objects  # key -> dict(bytes, LastModified)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key]["body"])}

    def get_paginator(self, name):
        objs = self.objects

        class P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "LastModified": v["at"]}
                        for k, v in objs.items()
                        if k.startswith(Prefix)
                    ]
                }

        return P()


def recorder(frame):
    sql = []

    def q(text):
        sql.append(text)
        return frame.copy()

    q.sql = sql
    return q


def test_since_is_inclusive_kst_window():
    assert model_io._since(1, TODAY) == "2026-10-25"
    assert model_io._since(30, TODAY) == "2026-09-26"
    with pytest.raises(ValueError):
        model_io._since(0, TODAY)


def test_every_score_query_has_review_date_condition():
    frame = pd.DataFrame(
        {
            "review_date": ["2026-10-21"], "model_version": ["v"], "aspect": ["배송"], "score": ["2"],
            "review_count": ["3"], "analyzed_review_count": ["3"], "zero_aspect_review_count": ["0"],
            "review_id": ["R1"], "score_a": ["1"], "score_b": ["2"],
        }
    )  # fmt: skip
    q = recorder(frame)
    model_io.review_daily(q, CFG, 7)
    model_io.score_daily(q, CFG, 7)
    model_io.score_diff(q, CFG, "a_v", "b_v", 7)
    assert all("review_date >=" in s for s in q.sql)


def test_score_daily_converts_types():
    frame = pd.DataFrame(
        {
            "review_date": ["2026-10-21"],
            "model_version": ["v"],
            "aspect": ["배송"],
            "score": ["-1"],
            "review_count": ["5"],
        }
    )
    out = model_io.score_daily(recorder(frame), CFG, 7)
    assert out.score.iloc[0] == -1 and out.review_count.iloc[0] == 5
    assert pd.api.types.is_datetime64_any_dtype(out.review_date)


def test_score_diff_rejects_bad_version_name():
    with pytest.raises(ValueError):
        model_io.score_diff(recorder(pd.DataFrame()), CFG, "a'; DROP", "b", 7)


def test_score_diff_too_many_rows_is_an_error_not_a_partial_result():
    big = pd.DataFrame(
        {"review_id": ["R"] * (model_io.MAX_ROWS + 1), "aspect": ["a"] * (model_io.MAX_ROWS + 1),
         "score_a": ["1"] * (model_io.MAX_ROWS + 1), "score_b": ["1"] * (model_io.MAX_ROWS + 1),
         "review_date": ["2026-10-21"] * (model_io.MAX_ROWS + 1)}
    )  # fmt: skip
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.score_diff(recorder(big), CFG, "a", "b", 7)


def silver_s3(status="PASS", run_id="reviews-v2-20261024T155307Z"):
    body = json.dumps({"run_id": run_id, "status": status}).encode()
    return FakeS3({"silver/runtime/reviews/current.json": {"body": body, "at": datetime.now(UTC)}})


def test_current_run_requires_pass():
    assert model_io.current_silver_run(silver_s3(), CFG).startswith("reviews-v2")
    # PARTIAL 도 숨기지 않고 읽는다
    assert model_io.current_silver_run(silver_s3(status="PARTIAL"), CFG).startswith("reviews-v2")
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.current_silver_run(silver_s3(status="FAIL"), CFG)
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.current_silver_run(FakeS3({}), CFG)
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.current_silver_run(silver_s3(), model_io.Config())  # 위치 설정 없음


def test_review_meta_reads_text_only_for_given_ids_and_drops_bad_ids():
    frame = pd.DataFrame(
        {"review_id": ["R1"], "product_id": ["P"], "product_name": ["n"], "category": ["c"], "rating": ["5"],
         "review_date": ["2026-10-21"], "review_text": ["본문"]}
    )  # fmt: skip
    q = recorder(frame)
    out = model_io.review_meta(q, silver_s3(), CFG, ("R1", "x'; DROP TABLE t; --", "R1"))
    sql = q.sql[0]
    assert "text AS review_text" in sql and "review_id IN ('R1')" in sql  # 지정한 id 만
    assert "run_id = 'reviews-v2-20261024T155307Z'" in sql
    assert "DROP" not in sql and sql.count("'R1'") == 1
    assert list(out.columns) == [
        "review_id", "product_id", "product_name", "category", "rating", "review_date", "review_text",
    ]  # fmt: skip
    assert model_io.review_meta(q, silver_s3(), CFG, ()).empty


def test_aggregate_queries_never_read_review_text():
    frame = pd.DataFrame(
        {"review_date": ["2026-10-21"], "model_version": ["v"], "aspect": ["a"], "score": ["1"], "review_count": ["1"],
         "analyzed_review_count": ["1"], "zero_aspect_review_count": ["0"], "review_id": ["R"], "score_a": ["1"], "score_b": ["1"],
         "last_analyzed_at": ["2026-10-25T00:00:00"], "analyzed_reviews": ["1"]}
    )  # fmt: skip
    q = recorder(frame)
    model_io.review_daily(q, CFG, 7)
    model_io.score_daily(q, CFG, 7)
    model_io.score_diff(q, CFG, "a", "b", 7)
    model_io.registry_stats(q, CFG)
    assert all("review_text" not in s and ".text" not in s for s in q.sql)


def test_unscored_remaining_counts_against_current_run_and_number():
    q = recorder(pd.DataFrame({"n": ["17011"]}))
    assert model_io.unscored_remaining(q, silver_s3(), CFG, "1.0") == 17011
    assert "DECIMAL '1.0'" in q.sql[0] and "l.review_id IS NULL" in q.sql[0]
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.unscored_remaining(q, silver_s3(), CFG, "1")


def summary(at, n_in, failed, zero):
    d = {"모델버전": "v", "모델번호": "1.0", "분석시각": at, "입력후기": n_in, "출력행": 2 * n_in, "속성없음후기": zero,
         "파싱실패": failed, "초": 100, "초당": 1.0}  # fmt: skip
    return json.dumps(d, ensure_ascii=False).encode()


def test_runs_reads_summaries_newest_first_and_computes_scored():
    t = datetime(2026, 10, 25, tzinfo=UTC)
    s3 = FakeS3(
        {
            "staging/review-score/_summary_scores_v_1.json": {"body": summary("2026-10-25T01:00:00+00:00", 100, 5, 2), "at": t},
            "staging/review-score/_summary_scores_v_2.json": {"body": summary("2026-10-25T02:00:00+00:00", 50, 0, 0), "at": t.replace(hour=2)},
            "staging/review-score/year=2026/month=10/day=21/scores_v.parquet": {"body": b"", "at": t},
        }
    )  # fmt: skip
    out = model_io.runs(s3, CFG)
    assert list(out.input_reviews) == [50, 100]  # 최신 먼저, parquet 파일은 제외
    assert out.scored_reviews.tolist() == [50, 93]  # 입력 - 파싱 실패 - 속성 0개
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.runs(s3, model_io.Config())  # 위치 설정 없음


def test_runs_read_failure_is_unavailable_not_empty():
    class Broken(FakeS3):
        def get_paginator(self, name):
            raise RuntimeError("denied")

    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.runs(Broken({}), CFG)


def test_config_rejects_bad_names():
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.Config(database="x; drop").check()


def list_frame():
    # 가짜 문장만 쓴다(실제 후기 원문을 시험 데이터에 넣지 않는다)
    rows = [
        ("R2", "2026-10-22", "P1", "상품A", "4", "가짜 문장 둘", "배송", "2", "v1"),
        ("R2", "2026-10-22", "P1", "상품A", "4", "가짜 문장 둘", "가격·가성비", "-1", "v1"),
        ("R1", "2026-10-21", "P2", "상품B", "5", "가짜 문장 하나", "냄새", "1", "v1"),
    ]
    cols = [
        "review_id",
        "review_date",
        "product_id",
        "product_name",
        "rating",
        "review_text",
        "aspect",
        "score",
        "model_version",
    ]
    return pd.DataFrame(rows, columns=cols)  # fmt: skip


def test_review_list_sql_filters_and_one_row_per_review():
    q = recorder(list_frame())
    out = model_io.review_list(
        q, silver_s3(), CFG, 30, product_id="P1", aspect="배송", scores=(-2, -1)
    )
    sql = q.sql[0]
    assert "s.run_id = 'reviews-v2-20261024T155307Z'" in sql
    assert sql.count("review_date >= DATE") >= 2  # 후기 쪽·점수 쪽 모두 파티션 조건
    assert (
        "s.product_id = 'P1'" in sql and "l.aspect = '배송'" in sql and "l.score IN (-2, -1)" in sql
    )
    assert "review_aspect_scores_latest" in sql and f"LIMIT {model_io.LIST_LIMIT}" in sql
    assert list(out.columns) == model_io.LIST_COLS
    assert out.review_id.tolist() == ["R2", "R1"]  # 최근 작성일 먼저, 후기 하나 = 한 줄
    assert "배송 +2" in out.loc[0, "scores"] and "가격·가성비 -1" in out.loc[0, "scores"]
    assert out.loc[0, "aspect_count"] == 2 and out.loc[0, "review_text"] == "가짜 문장 둘"


def test_review_list_rejects_bad_filters_and_empty_result_is_ok():
    q = recorder(list_frame())
    for kwargs in (
        {"product_id": "P1'; DROP"},
        {"aspect": "배송'; --"},
        {"scores": (3,)},
        {"scores": ("1",)},
    ):
        with pytest.raises(ValueError):
            model_io.review_list(q, silver_s3(), CFG, 30, **kwargs)
    empty = model_io.review_list(recorder(list_frame().iloc[0:0]), silver_s3(), CFG, 30)
    assert empty.empty and list(empty.columns) == model_io.LIST_COLS
    with pytest.raises(model_io.ModelDataUnavailable):
        model_io.review_list(
            q, silver_s3(status="FAIL"), CFG, 30
        )  # PASS·PARTIAL 이 아닌 실행은 읽지 않는다
