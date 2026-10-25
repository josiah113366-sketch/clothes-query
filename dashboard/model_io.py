"""[데이터 관리 > 감성분석 모델] 실데이터 조회. 더미 없음 (lemin 2026-10-25).

읽는 곳 (모두 읽기 전용)
  Athena DB (기본 clothes_query_dev_review_score, athena-review-score 스택)
    review_aspect_scores_latest 뷰: 후기마다 model_version_no 가 가장 큰 결과 (Gold 가 읽는 값. 후기 목록이 쓴다)
    review_aspect_scores        점수 테이블 (review_id, aspect, score, model_version, model_version_no, analyzed_at, review_date)
    review_score_log            후기별 점수 로그 (속성이 0개인 후기도 n_aspects = 0 으로 한 줄)
    silver_reviews_runs         Silver 리뷰 실행 출력 (run_id 파티션 프로젝션. 상품·작성일·별점과, 점수 차가 큰 후기에 한해 원문 text)
  S3
    staging/review-score/_summary_scores_*.json   Job 한 번의 요약 (입력 후기·파싱 실패·속성 0개·소요 시간)
    silver/runtime/reviews/current.json           가장 최근 Silver 실행 (run_id, status)
    review-score/model-registry/releases/         모델 버전·패치노트·평가 지표 (data.py 의 _read_releases 가 읽는다)

원칙
  - 읽기에 실패하거나 연결 설정이 없으면 가짜 값을 만들지 않고 ModelDataUnavailable 을 던진다. 화면(models.py)은 그 탭을 회색 '미연결'로 표시한다.
  - 점수·로그 쿼리는 review_date 조건을 반드시 건다 (Iceberg 파티션). 기간은 호출하는 쪽이 정한다.
  - 후기 원문은 '점수 차가 큰 후기' 확인용으로 review_id 몇 건에 한해서만 가져온다(최대 500건, lemin 2026-10-25 결정). 팀 내부용이다:
    대시보드는 로그인·허용 IP 뒤에서만 열리고, 원문을 외부 서비스로 보내거나 Git 에 넣지 않는다. 집계 쿼리는 원문을 읽지 않는다.
  - 모델 버전(이름)을 섞어 합산하지 않는다. 모든 집계는 model_version 별로 나눠서 돌려준다.

이 모듈은 streamlit 에 의존하지 않는다: query(sql) -> 문자열 DataFrame 함수와 s3 클라이언트를 받아 쓰므로 가짜 함수로 시험할 수 있다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
NAME_RE = re.compile(r"[A-Za-z0-9_]+")
RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")
ASPECT_ORDER = [  # 표시 순서(모델 속성 11개, review-analysis/deploy/score_batch.py 의 ASPECTS 와 같다)
    "재질·촉감", "사이즈·핏", "색상·디자인", "품질·내구성", "가격·가성비", "냄새",
    "세탁·관리", "활용성·사용감", "배송", "포장", "교환·환불·CS",
]  # fmt: skip
MAX_ROWS = 100_000  # 한 번에 가져올 최대 행. 넘으면 일부만 보여 주지 않고 오류로 알린다


class ModelDataUnavailable(Exception):
    """연결 안 됨(설정 없음)·읽기 실패. 메시지는 화면에 그대로 보여 준다."""


@dataclass(frozen=True)
class Config:
    database: str = "clothes_query_dev_review_score"
    scores_table: str = "review_aspect_scores"
    log_table: str = "review_score_log"
    silver_runs_table: str = "silver_reviews_runs"
    latest_view: str = "review_aspect_scores_latest"
    staging_uri: str = ""  # s3://<버킷>/staging/review-score/ (끝에 /)
    silver_root_uri: str = ""  # s3://<버킷>/silver/runtime/reviews/ (끝에 /)

    def check(self) -> None:
        for n in (
            self.database,
            self.scores_table,
            self.log_table,
            self.silver_runs_table,
            self.latest_view,
        ):
            if not NAME_RE.fullmatch(n):
                raise ModelDataUnavailable(f"데이터베이스·테이블 이름 형식 오류: {n!r}")


def split_s3(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ModelDataUnavailable(f"S3 주소 형식이 아닙니다: {uri!r}")
    bucket, _, key = uri[5:].partition("/")
    return bucket, key


def _since(days: int, today: pd.Timestamp | None = None) -> str:
    """오늘(KST) 포함 최근 days 일의 시작일 'YYYY-MM-DD' (review_date 파티션 조건용)."""
    if not isinstance(days, int) or not 1 <= days <= 366:
        raise ValueError("days 는 1~366 이어야 합니다")
    today = (
        today
        if today is not None
        else pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    )
    return f"{today - pd.Timedelta(days=days - 1):%Y-%m-%d}"


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _guard(df: pd.DataFrame, what: str) -> pd.DataFrame:
    if len(df) > MAX_ROWS:
        raise ModelDataUnavailable(f"{what} 행이 {MAX_ROWS:,}개를 넘습니다. 기간을 줄여 주세요")
    return df


# ------------------------------------------------------------------ 점수 로그·점수 테이블
def registry_stats(query, cfg: Config, days: int = 366) -> pd.DataFrame:
    """모델 버전(이름)별 마지막 분석 시각(UTC)·분석한 후기 수. 컬럼: model_version, last_analyzed_at, analyzed_reviews."""
    cfg.check()
    df = query(
        "SELECT model_version, max(analyzed_at) AS last_analyzed_at, count(DISTINCT review_id) AS analyzed_reviews "
        f"FROM {cfg.database}.{cfg.log_table} WHERE review_date >= DATE '{_since(days)}' GROUP BY model_version"
    )
    df["last_analyzed_at"] = pd.to_datetime(df["last_analyzed_at"], utc=True, errors="coerce")
    return _num(df, ["analyzed_reviews"])


def review_daily(query, cfg: Config, days: int) -> pd.DataFrame:
    """작성일(KST) × 모델 버전별 분석한 후기 수. 컬럼: review_date, model_version, analyzed_review_count, zero_aspect_review_count."""
    cfg.check()
    df = query(
        "SELECT CAST(review_date AS varchar) AS review_date, model_version, count(DISTINCT review_id) AS analyzed_review_count, "
        "count(DISTINCT CASE WHEN n_aspects = 0 THEN review_id END) AS zero_aspect_review_count "
        f"FROM {cfg.database}.{cfg.log_table} WHERE review_date >= DATE '{_since(days)}' GROUP BY 1, 2 ORDER BY 1, 2"
    )
    df["review_date"] = pd.to_datetime(df["review_date"])
    return _num(df, ["analyzed_review_count", "zero_aspect_review_count"])


def score_daily(query, cfg: Config, days: int) -> pd.DataFrame:
    """작성일 × 모델 버전 × 속성 × 점수별 후기 수. 컬럼: review_date, model_version, aspect, score, review_count."""
    cfg.check()
    df = query(
        "SELECT CAST(review_date AS varchar) AS review_date, model_version, aspect, score, count(*) AS review_count "
        f"FROM {cfg.database}.{cfg.scores_table} WHERE review_date >= DATE '{_since(days)}' GROUP BY 1, 2, 3, 4"
    )
    df["review_date"] = pd.to_datetime(df["review_date"])
    return _num(df, ["score", "review_count"])


def score_diff(query, cfg: Config, model_a: str, model_b: str, days: int) -> pd.DataFrame:
    """같은 후기·속성에 대한 두 버전의 점수. 두 버전이 모두 점수를 낸 쌍만. 컬럼: review_id, aspect, score_a, score_b, review_date."""
    cfg.check()
    for v in (model_a, model_b):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v or ""):
            raise ValueError(f"모델 버전 이름 형식 오류: {v!r}")
    since = _since(days)
    t = f"{cfg.database}.{cfg.scores_table}"
    df = query(
        "SELECT a.review_id, a.aspect, a.score AS score_a, b.score AS score_b, CAST(a.review_date AS varchar) AS review_date "
        f"FROM {t} a JOIN {t} b ON a.review_id = b.review_id AND a.aspect = b.aspect AND a.review_date = b.review_date "
        f"WHERE a.model_version = '{model_a}' AND b.model_version = '{model_b}' "
        f"AND a.review_date >= DATE '{since}' AND b.review_date >= DATE '{since}' LIMIT {MAX_ROWS + 1}"
    )
    df["review_date"] = pd.to_datetime(df["review_date"])
    return _guard(_num(df, ["score_a", "score_b"]), "버전 비교")


# ------------------------------------------------------------------ Silver 리뷰 실행 (상품·작성일·별점·원문)
def current_silver_run(s3, cfg: Config) -> str:
    """silver/runtime/reviews/current.json 의 run_id. status 가 PASS 가 아니면 읽지 않는다."""
    if not cfg.silver_root_uri:
        raise ModelDataUnavailable("Silver 리뷰 위치(REVIEW_SILVER_ROOT_URI)가 설정되지 않았습니다")
    bucket, root = split_s3(cfg.silver_root_uri)
    try:
        info = json.loads(
            s3.get_object(Bucket=bucket, Key=root.rstrip("/") + "/current.json")["Body"].read()
        )
    except Exception as e:
        raise ModelDataUnavailable(
            f"Silver current.json 을 읽지 못했습니다 ({type(e).__name__})"
        ) from e
    run_id = info.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ModelDataUnavailable("current.json 에 올바른 run_id 가 없습니다")
    if info.get("status") != "PASS":
        raise ModelDataUnavailable(
            f"최근 Silver 실행 {run_id} 의 status 가 PASS 가 아닙니다 ({info.get('status')!r})"
        )
    return run_id


def unscored_remaining(query, s3, cfg: Config, model_version_no: str) -> int:
    """현재 Silver 실행의 후기 중 점수 로그(해당 모델 번호)에 없는 후기 수 = 미점수 잔량."""
    cfg.check()
    if not re.fullmatch(r"\d{1,2}\.\d", model_version_no or ""):
        raise ModelDataUnavailable(f"모델 번호 형식 오류: {model_version_no!r}")
    run_id = current_silver_run(s3, cfg)
    d = f"{cfg.database}"
    df = query(
        "SELECT count(*) AS n "
        f"FROM {d}.{cfg.silver_runs_table} s LEFT JOIN {d}.{cfg.log_table} l "
        f"ON l.review_id = s.review_id AND l.review_date = s.review_date_kst AND l.model_version_no = DECIMAL '{model_version_no}' "
        f"WHERE s.run_id = '{run_id}' AND l.review_id IS NULL AND s.text IS NOT NULL AND trim(s.text) <> ''"
    )
    return int(df["n"].iloc[0])


def review_meta(query, s3, cfg: Config, review_ids: tuple[str, ...]) -> pd.DataFrame:
    """후기 id 의 상품·카테고리·별점·작성일·원문. 컬럼: review_id, product_id, product_name, category, rating, review_date, review_text.
    현재 Silver 실행에 없는 id 는 결과에 없다."""
    cfg.check()
    ids = [i for i in dict.fromkeys(review_ids) if ID_RE.fullmatch(i)][:500]
    cols = [
        "review_id",
        "product_id",
        "product_name",
        "category",
        "rating",
        "review_date",
        "review_text",
    ]
    if not ids:
        return pd.DataFrame(columns=cols)
    run_id = current_silver_run(s3, cfg)
    quoted = ", ".join(f"'{i}'" for i in ids)
    df = query(
        "SELECT review_id, product_id, product_name, category, rating, CAST(review_date_kst AS varchar) AS review_date, text AS review_text "
        f"FROM {cfg.database}.{cfg.silver_runs_table} WHERE run_id = '{run_id}' AND review_id IN ({quoted})"
    )
    df["review_date"] = pd.to_datetime(df["review_date"])
    return _num(df, ["rating"]).drop_duplicates("review_id")


# ------------------------------------------------------------------ 후기 목록 (원문 + Gold 가 읽는 최신 속성 점수)
LIST_LIMIT = 200  # 한 번에 보여 줄 최대 후기 수. 넘는 후기는 최근 작성일 순으로 잘라 낸다(필터를 좁혀 보도록 화면에 안내)
LIST_COLS = [
    "review_id", "review_date", "product_id", "product_name", "rating", "review_text", "scores", "aspect_count", "model_version",
]  # fmt: skip
SAFE_TEXT_RE = re.compile(
    r"[^'\\;\x00-\x1f]{1,40}"
)  # 속성 이름처럼 SQL 문자열에 넣는 짧은 값(따옴표·세미콜론·제어문자 금지)


def review_list(
    query,
    s3,
    cfg: Config,
    days: int,
    product_id: str = "",
    aspect: str = "",
    scores: tuple = (),
    limit: int = LIST_LIMIT,
) -> pd.DataFrame:
    """최근 Silver 실행(PASS)의 후기 원문 + 뷰(review_aspect_scores_latest)의 속성별 점수. 후기 하나 = 한 줄.

    필터: 작성일(최근 days 일, review_date 파티션 조건), 상품 id, 속성, 점수. 속성·점수 필터는 "그 속성이 그 점수인 후기"를 고르고,
    고른 뒤에는 그 후기의 모든 속성 점수를 보여 준다(scores 열: '배송 +2 · 가격 -1'). 최대 limit 건(최근 작성일 순).
    원문은 팀 내부용이다(허용 IP·로그인 뒤에서만 열림, 외부 반출 금지). 점수가 아직 없는 후기는 목록에 나오지 않는다.
    """
    cfg.check()
    since = _since(days)
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit 범위 오류")
    run_id = current_silver_run(s3, cfg)
    d = cfg.database
    sv, lv = f"{d}.{cfg.silver_runs_table}", f"{d}.{cfg.latest_view}"
    s_where = [f"s.run_id = '{run_id}'", f"s.review_date_kst >= DATE '{since}'"]
    l_where = [
        "l.review_id = s.review_id",
        "l.review_date = s.review_date_kst",
        f"l.review_date >= DATE '{since}'",
    ]
    if product_id:
        if not ID_RE.fullmatch(product_id):
            raise ValueError(f"상품 id 형식 오류: {product_id!r}")
        s_where.append(f"s.product_id = '{product_id}'")
    if aspect:
        if not SAFE_TEXT_RE.fullmatch(aspect):
            raise ValueError(f"속성 이름 형식 오류: {aspect!r}")
        l_where.append(f"l.aspect = '{aspect}'")
    if scores:
        if not all(isinstance(x, int) and -2 <= x <= 2 for x in scores):
            raise ValueError("점수는 -2~2 정수여야 합니다")
        l_where.append(f"l.score IN ({', '.join(str(int(x)) for x in scores)})")
    sql = (
        "WITH pick AS ("
        "SELECT s.review_id, s.review_date_kst, s.product_id, s.product_name, s.rating, s.text AS review_text "
        f"FROM {sv} s WHERE {' AND '.join(s_where)} "
        f"AND EXISTS (SELECT 1 FROM {lv} l WHERE {' AND '.join(l_where)}) "
        f"ORDER BY s.review_date_kst DESC, s.review_id LIMIT {limit}) "
        "SELECT p.review_id, CAST(p.review_date_kst AS varchar) AS review_date, p.product_id, p.product_name, p.rating, p.review_text, "
        "l.aspect, l.score, l.model_version "
        f"FROM pick p JOIN {lv} l ON l.review_id = p.review_id AND l.review_date = p.review_date_kst "
        f"WHERE l.review_date >= DATE '{since}'"
    )
    df = _num(query(sql), ["rating", "score"])
    if df.empty:
        return pd.DataFrame(columns=LIST_COLS)
    df["review_date"] = pd.to_datetime(df["review_date"])
    order = {a: i for i, a in enumerate(ASPECT_ORDER)}
    df = df.assign(_o=df.aspect.map(lambda a: order.get(a, len(order)))).sort_values(
        ["review_id", "_o", "aspect"]
    )
    keys = ["review_id", "review_date", "product_id", "product_name", "rating", "review_text"]
    out = (
        df.groupby(keys, sort=False, dropna=False)
        .agg(
            aspect_count=("aspect", "size"),
            model_version=("model_version", "first"),
        )
        .reset_index()
    )
    text = (
        df.assign(t=df.aspect + " " + df.score.map(lambda x: f"{int(x):+d}"))
        .groupby("review_id", sort=False)["t"]
        .agg(" · ".join)
    )
    out["scores"] = out.review_id.map(text)
    return out.sort_values(["review_date", "review_id"], ascending=[False, True]).reset_index(
        drop=True
    )[LIST_COLS]


# ------------------------------------------------------------------ Job 실행 요약 (S3 _summary_scores_*.json)
RUN_COLS = [
    "analyzed_at",
    "model_version",
    "model_version_no",
    "input_reviews",
    "scored_reviews",
    "zero_aspect_reviews",
    "parse_failed",
    "output_rows",
    "seconds",
    "per_second",
]


def runs(s3, cfg: Config, limit: int = 60) -> pd.DataFrame:
    """Job 한 번 = 한 줄. S3 의 최근 limit 개 요약 JSON. 컬럼은 RUN_COLS.
    scored_reviews = 입력 - 파싱 실패 - 속성 0개 (점수가 한 개 이상 나온 후기). 실패한 Job 은 요약이 없어 여기에 나오지 않는다."""
    if not cfg.staging_uri:
        raise ModelDataUnavailable(
            "점수 staging 위치(REVIEW_SCORE_STAGING_URI)가 설정되지 않았습니다"
        )
    bucket, prefix = split_s3(cfg.staging_uri)
    prefix = prefix.rstrip("/") + "/_summary_scores_"
    try:
        objs = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            objs += page.get("Contents", [])
        objs = sorted(objs, key=lambda o: o["LastModified"], reverse=True)[:limit]
        rows = []
        for o in objs:
            d = json.loads(s3.get_object(Bucket=bucket, Key=o["Key"])["Body"].read())
            n_in, failed, zero = (
                int(d.get("입력후기", 0)),
                int(d.get("파싱실패", 0)),
                int(d.get("속성없음후기", 0)),
            )
            rows.append(
                {
                    "analyzed_at": pd.to_datetime(d.get("분석시각"), utc=True, errors="coerce"),
                    "model_version": d.get("모델버전"),
                    "model_version_no": d.get("모델번호"),
                    "input_reviews": n_in,
                    "scored_reviews": max(n_in - failed - zero, 0),
                    "zero_aspect_reviews": zero,
                    "parse_failed": failed,
                    "output_rows": int(d.get("출력행", 0)),
                    "seconds": float(d.get("초", np.nan)),
                    "per_second": float(d.get("초당", np.nan)),
                }
            )
    except ModelDataUnavailable:
        raise
    except Exception as e:
        raise ModelDataUnavailable(f"실행 요약을 읽지 못했습니다 ({type(e).__name__})") from e
    return pd.DataFrame(rows, columns=RUN_COLS)
