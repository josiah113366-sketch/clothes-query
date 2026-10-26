"""Gold A 완료 실행을 한 화면 동안 고정해서 읽는 Athena 어댑터."""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

TABLES = {
    "order_sales_hourly": (
        "trade",
        "hour_start_kst",
        "hour_start_kst order_count paid_order_count approved_amount",
    ),
    "product_sales_daily": (
        "trade",
        "sales_date_kst",
        "sales_date_kst article_id product_code paid_order_count sold_quantity item_sales_amount",
    ),
    "funnel_daily": (
        "funnels",
        "funnel_date_kst",
        "funnel_date_kst article_id product_code view_sessions cart_sessions order_sessions paid_sessions cart_order_sessions view_to_cart_rate view_to_order_rate view_to_paid_rate cart_to_order_rate order_to_paid_rate",
    ),
    "funnel_session_product": (
        "funnels",
        "first_view_at_kst",
        "session_id article_id product_code first_view_at_kst first_cart_at_kst first_order_at_kst first_paid_at_kst has_view has_cart has_order has_paid ordered_after_cart",
    ),
    "review_product_daily": (
        "reviews",
        "review_date_kst",
        "review_date_kst article_id product_code review_count rating_sum low_rating_count average_rating low_rating_rate",
    ),
    "review_aspect_daily": (
        "reviews",
        "review_date_kst",
        "review_date_kst article_id product_code aspect model_version model_version_no scored_review_count score_sum score_neg2_count score_neg1_count score_zero_count score_pos1_count score_pos2_count average_score",
    ),
}
COUNTS = {
    "order_count",
    "paid_order_count",
    "approved_amount",
    "sold_quantity",
    "item_sales_amount",
    "view_sessions",
    "cart_sessions",
    "order_sessions",
    "paid_sessions",
    "cart_order_sessions",
    "review_count",
    "rating_sum",
    "low_rating_count",
    "scored_review_count",
    "score_sum",
    "score_neg2_count",
    "score_neg1_count",
    "score_zero_count",
    "score_pos1_count",
    "score_pos2_count",
}
RATES = {
    "view_to_cart_rate",
    "view_to_order_rate",
    "view_to_paid_rate",
    "cart_to_order_rate",
    "order_to_paid_rate",
    "average_rating",
    "low_rating_rate",
    "average_score",
}
HOLD_COLUMNS = [
    "table_name",
    "key_json",
    "reason",
    "previous_result_available",
    "last_normal_result_json",
]


class GoldAError(RuntimeError):
    """연결 실패를 화면에서 더미 값과 구분할 때 쓰는 오류."""


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class GoldAReader:
    def __init__(
        self,
        client,
        workgroup,
        database="gold_a",
        timeout=60,
        today=None,
        sleep=time.sleep,
        clock=time.monotonic,
        max_rows=100000,
        mode="operation",
        selected_runs=None,
        funnel_evidence=None,
    ):
        if not workgroup or not re.fullmatch(r"[a-z][a-z0-9_]*", database):
            raise GoldAError("Gold A의 Athena 작업그룹·DB 설정을 확인해 주세요.")
        self.client, self.workgroup, self.database = client, workgroup, database
        self.timeout, self.sleep, self.clock, self.max_rows = timeout, sleep, clock, max_rows
        self.today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
        self.runs, self.cache, self.holds_cache = {}, {}, {}
        if mode not in {"operation", "demo"}:
            raise GoldAError("Gold 조회 모드가 올바르지 않습니다.")
        self.mode, self.selected_runs, self.funnel_evidence = mode, selected_runs or {}, funnel_evidence

    def run_options(self, channel):
        if channel != "trade":
            raise GoldAError("실행 선택은 거래 공개 결과만 지원합니다.")
        return self.query(
            f"SELECT run_id, completed_at, quality_status FROM {self.database}.gold_runs "
            "WHERE channel = 'trade' AND status = 'COMPLETED' ORDER BY completed_at DESC, run_id DESC LIMIT 20"
        )

    def query(self, sql, *, max_rows=None):
        # 거래 상품 집계 140,807행을 지원하되 다른 업무의 기존 한도는 유지한다.
        row_limit = self.max_rows if max_rows is None else max_rows
        qid = None
        try:
            qid = self.client.start_query_execution(
                QueryString=sql,
                WorkGroup=self.workgroup,
                QueryExecutionContext={"Database": self.database},
                ResultReuseConfiguration={"ResultReuseByAgeConfiguration": {"Enabled": False}},
            )["QueryExecutionId"]
            deadline = self.clock() + self.timeout
            while True:
                state = self.client.get_query_execution(QueryExecutionId=qid)["QueryExecution"][
                    "Status"
                ]["State"]
                if state == "SUCCEEDED":
                    break
                if state in {"FAILED", "CANCELLED"}:
                    raise GoldAError(
                        "Athena 조회에 실패했습니다. 카탈로그·권한·쿼리 상태를 확인해 주세요."
                    )
                if self.clock() >= deadline:
                    raise GoldAError("Athena 조회 대기 시간이 초과됐습니다.")
                self.sleep(0.5)
            columns, records, first_row = None, [], True
            for page in self.client.get_paginator("get_query_results").paginate(
                QueryExecutionId=qid
            ):
                current = [c["Name"] for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
                if columns is None:
                    columns = current
                elif columns != current:
                    raise GoldAError("Athena 결과의 컬럼이 조회 도중 달라졌습니다.")
                for row in page["ResultSet"]["Rows"]:
                    values = [v.get("VarCharValue") for v in row["Data"]]
                    is_header = first_row and values == columns
                    first_row = False
                    if is_header:
                        continue
                    if len(values) != len(columns):
                        raise GoldAError("Athena 결과의 열 개수가 잘못됐습니다.")
                    records.append(values)
                    if len(records) > row_limit:
                        raise GoldAError(
                            "조회 결과 한도를 초과했습니다. 기간을 줄이거나 조회 구성을 확인해 주세요."
                        )
            return pd.DataFrame(records, columns=columns)
        except GoldAError:
            if qid:
                try:
                    self.client.stop_query_execution(QueryExecutionId=qid)
                except Exception:  # noqa: BLE001 -- 취소 실패가 원래 조회 오류를 덮지 않는다.
                    logging.getLogger(__name__).warning(
                        "Athena 실패 쿼리 취소를 확인하지 못했습니다."
                    )
            raise
        except Exception as error:
            raise GoldAError(
                "Gold A 실데이터를 조회하지 못했습니다. 연결·권한·테이블 설정을 확인해 주세요."
            ) from error

    def _acknowledged_funnel(self):
        if self.funnel_evidence is None:
            raise GoldAError("퍼널 부분 결과 근거 조회 설정이 없습니다.")
        row = self.funnel_evidence.latest()
        actual = self.query(" UNION ALL ".join(
            f"SELECT '{name}' AS metric, count(*) AS n FROM {self.database}.{name}_runs "
            f"WHERE run_id = {literal(row['run_id'])}" + (" AND channel = 'funnels'" if name == "refresh_holds" else "")
            for name in ("funnel_daily", "funnel_session_product", "refresh_holds")
        ))
        if (list(actual.columns) != ["metric", "n"] or len(actual) != 3
                or dict(zip(actual.metric, actual.n.astype(int), strict=True)) != row["tables"]):
            raise GoldAError("부분 퍼널의 Athena 건수가 완료 manifest와 다릅니다.")
        if self.mode == "operation" and (row["quality_status"] != "PARTIAL" or row.get("coverage_status") != "BACKFILL_IN_PROGRESS"):
            raise GoldAError("완료 퍼널은 정식 공개 목록에서 확인해야 합니다.")
        row["demo_only"] = self.mode == "demo"
        row["partial_publication"] = self.mode == "operation"
        self.runs["funnels"] = row
        return row

    def run(self, channel):
        if channel not in {"trade", "funnels", "reviews"}:
            raise GoldAError("지원하지 않는 Gold A 업무입니다.")
        if channel not in self.runs:
            if self.mode == "demo" and channel == "funnels":
                return self._acknowledged_funnel()
            selection = self.selected_runs.get(channel) if self.mode == "demo" and channel == "trade" else None
            if selection and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", selection):
                raise GoldAError("선택한 Gold 실행 ID가 올바르지 않습니다.")
            df = self.query(
                f"SELECT run_id, completed_at, quality_status, held_scope_count, available_tables_json, source_manifest, silver_run_id "
                f"FROM {self.database}.gold_runs WHERE channel = {literal(channel)} AND status = 'COMPLETED' "
                + (f"AND run_id = {literal(selection)} " if selection else "")
                + "ORDER BY completed_at DESC, run_id DESC LIMIT 1"
            )
            if df.empty:
                if channel == "funnels" and self.funnel_evidence is not None:
                    return self._acknowledged_funnel()
                self.runs[channel] = None
            else:
                row = df.iloc[0].to_dict()
                try:
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", row["run_id"]) or row[
                        "quality_status"
                    ] not in {"PASS", "PARTIAL"}:
                        raise ValueError()
                    row["tables"] = json.loads(row["available_tables_json"])
                    if not isinstance(row["tables"], dict) or any(
                        type(v) is not int or v < 0 for v in row["tables"].values()
                    ):
                        raise ValueError()
                    row["held_scope_count"] = int(row["held_scope_count"])
                    if row["held_scope_count"] < 0:
                        raise ValueError()
                    required = {name for name, spec in TABLES.items() if spec[0] == channel}
                    if channel == "reviews":
                        required.discard("review_aspect_daily")
                    else:
                        required.add("refresh_holds")
                    if not required.issubset(row["tables"]):
                        raise ValueError()
                    if (row["quality_status"] == "PASS") != (row["held_scope_count"] == 0):
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    raise GoldAError("Gold A 완료 목록의 형식이 계약과 다릅니다.") from None
                self.runs[channel] = row
                row["scope"] = "공개 실행의 집계 범위 · 전체 원천 처리 범위는 미검증"
                row["demo_only"] = self.mode == "demo" and channel == "trade"
        return self.runs[channel]

    def holds(self, channel):
        run = self.run(channel)
        if channel not in self.holds_cache:
            if not run or channel == "reviews":
                if run and run["held_scope_count"]:
                    raise GoldAError("리뷰 완료 결과에 지원하지 않는 보류 정보가 있습니다.")
                df = pd.DataFrame(columns=HOLD_COLUMNS)
            else:
                df = self.query(
                    f"SELECT {', '.join(HOLD_COLUMNS)} FROM {self.database}.refresh_holds_runs "
                    f"WHERE channel = {literal(channel)} AND run_id = {literal(run['run_id'])}"
                )
                if (
                    len(df) != run["tables"].get("refresh_holds")
                    or len(df) != run["held_scope_count"]
                ):
                    raise GoldAError("지표와 보류 목록의 공개 건수가 일치하지 않습니다.")
                if list(df.columns) != HOLD_COLUMNS:
                    raise GoldAError("보류 목록의 컬럼이 배포 명세와 다릅니다.")
                if not df.previous_result_available.isin(["true", "false"]).all():
                    raise GoldAError("보류 목록의 이전 결과 상태가 잘못됐습니다.")
                df["previous_result_available"] = df.previous_result_available.eq("true")
            df.attrs.update(run_id=run["run_id"] if run else None, channel=channel)
            self.holds_cache[channel] = df
        return self.holds_cache[channel]

    def read(self, table, days=30, article_id=None, n=15):
        if table not in TABLES:
            raise GoldAError("지원하지 않는 Gold A 테이블입니다.")
        if type(days) is not int or not 1 <= days <= 366:
            raise GoldAError("조회 기간은 1~366일이어야 합니다.")
        channel, date_column, fields = TABLES[table]
        columns = fields.split()
        run = self.run(channel)
        self.holds(channel)  # 보류를 확인하지 못한 결과를 정상 지표로 표시하지 않는다.
        state = "NO_RUN" if not run else "NOT_REQUESTED" if table not in run["tables"] else "OK"
        key = table, days, article_id, n
        if key in self.cache:
            return self.cache[key].copy()
        if state != "OK":
            df = pd.DataFrame(columns=columns)
        else:
            start = self.today - timedelta(days=days - 1)
            where = (
                f"run_id = {literal(run['run_id'])} AND CAST(substr(CAST({date_column} AS varchar),1,10) AS date) "
                f"BETWEEN DATE '{start}' AND DATE '{self.today}'"
            )
            suffix = (
                f" ORDER BY {date_column}, article_id"
                if table != "order_sales_hourly"
                else f" ORDER BY {date_column}"
            )
            if table == "funnel_session_product":
                if (
                    not isinstance(article_id, str)
                    or not article_id.strip()
                    or type(n) is not int
                    or not 1 <= n <= 500
                ):
                    raise GoldAError("퍼널 상세의 상품·조회 건수를 확인해 주세요.")
                where = f"run_id = {literal(run['run_id'])} AND article_id = {literal(article_id)}"
                suffix = f" ORDER BY first_view_at_kst DESC, session_id LIMIT {n}"
            sql = f"SELECT {', '.join(columns)} FROM {self.database}.{table}_runs WHERE {where}{suffix}"
            expanded_limit = channel == "trade" or (
                table == "funnel_daily" and run.get("coverage_status") == "BACKFILL_IN_PROGRESS")
            df = (self.query(sql, max_rows=max(self.max_rows, 250000))
                  if expanded_limit else self.query(sql))
            if list(df.columns) != columns:
                raise GoldAError("Gold A 조회 컬럼이 배포 명세와 다릅니다.")
        for column in columns:
            if column in COUNTS:
                df[column] = pd.to_numeric(df[column], errors="raise").astype("Int64")
            elif column in RATES:
                df[column] = pd.to_numeric(df[column], errors="raise").astype(float)
            elif column.endswith("_kst"):
                if column.startswith("first_") or column == "hour_start_kst":
                    df[column] = (
                        pd.to_datetime(df[column], utc=True, format="mixed")
                        .dt.tz_convert("Asia/Seoul")
                        .dt.tz_localize(None)
                    )
                else:
                    df[column] = pd.to_datetime(df[column])
            elif column in {"has_view", "has_cart", "has_order", "has_paid", "ordered_after_cart"}:
                if not df[column].isin(["true", "false"]).all():
                    raise GoldAError("퍼널 진행 상태의 형식이 잘못됐습니다.")
                df[column] = df[column].eq("true")
        if table == "review_aspect_daily":
            df["mentioned_review_count"] = df.scored_review_count
            df["positive_review_count"] = df.score_pos1_count + df.score_pos2_count
            df["neutral_review_count"] = df.score_zero_count
            df["negative_review_count"] = df.score_neg2_count + df.score_neg1_count
            df["negative_rate"] = df.negative_review_count / df.mentioned_review_count.where(
                df.mentioned_review_count != 0
            )
            df["model_key"] = df.model_version.fillna("") + df.model_version_no.map(
                lambda v: " · " + str(v) if pd.notna(v) else ""
            )
        df.attrs.update(state=state, channel=channel, run_id=run["run_id"] if run else None)
        self.cache[key] = df
        return df.copy()

    def funnel_summary(self, days, article_ids=None):
        """차트에 필요한 날짜별 합계만 읽는다. 상품별 비율을 평균내지 않는다."""
        if type(days) is not int or not 1 <= days <= 366:
            raise GoldAError("퍼널 조회 기간을 확인해 주세요.")
        if article_ids is not None and (not article_ids or len(article_ids) > 500
                or any(not isinstance(a, str) or not a.strip() for a in article_ids)):
            raise GoldAError("개별 상품은 1~500개를 선택하거나 전체 상품을 사용하세요.")
        fields = ["view_sessions", "cart_sessions", "order_sessions", "paid_sessions", "cart_order_sessions"]
        run = self.run("funnels")
        self.holds("funnels")
        if not run:
            result = pd.DataFrame(columns=["funnel_date_kst", *fields])
            result.attrs.update(state="NO_RUN", channel="funnels", run_id=None)
            return result
        start = self.today - timedelta(days=days - 1)
        where = (f"run_id = {literal(run['run_id'])} AND CAST(funnel_date_kst AS date) "
                 f"BETWEEN DATE '{start}' AND DATE '{self.today}'")
        if article_ids is not None:
            where += " AND article_id IN (" + ",".join(map(literal, sorted(set(article_ids)))) + ")"
        key = ("funnel_summary", days, None if article_ids is None else tuple(sorted(set(article_ids))))
        if key not in self.cache:
            result = self.query("SELECT funnel_date_kst, " + ", ".join(f"sum({f}) AS {f}" for f in fields)
                                + f" FROM {self.database}.funnel_daily_runs WHERE {where} GROUP BY funnel_date_kst ORDER BY funnel_date_kst")
            if list(result.columns) != ["funnel_date_kst", *fields]:
                raise GoldAError("퍼널 날짜별 합계의 형식이 다릅니다.")
            result["funnel_date_kst"] = pd.to_datetime(result["funnel_date_kst"])
            for field in fields:
                result[field] = pd.to_numeric(result[field], errors="raise").astype("Int64")
            result.attrs.update(state="OK", channel="funnels", run_id=run["run_id"])
            self.cache[key] = result
        return self.cache[key].copy()

    def funnel_order_paths(self, days, article_ids, expected):
        """동일 실행·첫 조회일·상품의 상세를 집계해 일별 표와 대조한다. 원본 행은 반환하지 않는다."""
        if type(days) is not int or not 1 <= days <= 366 or (article_ids is not None and not article_ids):
            raise GoldAError("주문 경로 분석 불가: 기간·상품을 확인해 주세요.")
        run = self.run("funnels")
        self.holds("funnels")
        if not run or "funnel_session_product" not in run["tables"]:
            raise GoldAError("주문 경로 분석 불가: 같은 실행의 상세가 없습니다.")
        selected = set(article_ids) if article_ids is not None else None
        known = set(self.products(("funnels",)).article_id) if selected is not None else None
        if selected is not None and not selected <= known:
            raise GoldAError("주문 경로 분석 불가: 공개 상품 범위와 다릅니다.")
        start = self.today - timedelta(days=days - 1)
        where = (f"run_id = {literal(run['run_id'])} AND "
                 "CAST(substr(CAST(first_view_at_kst AS varchar),1,10) AS date) "
                 f"BETWEEN DATE '{start}' AND DATE '{self.today}'")
        if selected is not None and selected != known:
            where += " AND article_id IN (" + ",".join(map(literal, sorted(selected))) + ")"
        expressions = {
            "view_sessions": "count_if(has_view)",
            "cart_sessions": "count_if(has_cart)",
            "order_sessions": "count_if(has_order)",
            "paid_sessions": "count_if(has_paid)",
            "cart_order_sessions": "count_if(ordered_after_cart)",
            "order_without_cart": "count_if(has_order AND NOT has_cart)",
            "order_with_cart": "count_if(has_order AND has_cart)",
            "invalid_rows": "count_if(has_view IS NULL OR has_cart IS NULL OR has_order IS NULL OR has_paid IS NULL OR ordered_after_cart IS NULL OR NOT has_view OR (has_paid AND NOT has_order) OR (ordered_after_cart AND NOT (has_cart AND has_order)))",
        }
        key = ("order_paths", days, None if selected is None else tuple(sorted(selected)))
        if key not in self.cache:
            self.cache[key] = self.query(
                "SELECT " + ", ".join(f"{expr} AS {name}" for name, expr in expressions.items())
                + f" FROM {self.database}.funnel_session_product_runs WHERE {where}"
            )
        df = self.cache[key]
        if len(df) != 1 or list(df.columns) != list(expressions):
            raise GoldAError("주문 경로 분석 불가: 상세 집계 형식이 다릅니다.")
        try:
            values = {name: int(df.iloc[0][name]) for name in expressions}
        except (ValueError, TypeError, OverflowError) as error:
            raise GoldAError("주문 경로 분석 불가: 집계 건수를 확인할 수 없습니다.") from error
        if (any(v < 0 for v in values.values()) or values["invalid_rows"]
                or any(values[name] != expected.get(name) for name in list(expressions)[:5])
                or values["order_with_cart"] + values["order_without_cart"] != values["order_sessions"]
                or values["cart_order_sessions"] > values["order_with_cart"]
                or values["order_sessions"] == 0):
            raise GoldAError("주문 경로 분석 불가: 같은 범위의 상세·일별 건수가 일치하지 않거나 주문이 없습니다.")
        values["without_cart_rate"] = values["order_without_cart"] / values["order_sessions"]
        return values

    def products(self, channels):
        key = ("products", tuple(channels))
        if key in self.cache:
            return self.cache[key].copy()
        frames = []
        metric = {
            "trade": "product_sales_daily",
            "funnels": "funnel_daily",
            "reviews": "review_product_daily",
        }
        for channel in channels:
            run = self.run(channel)
            if not run:
                continue
            self.holds(channel)
            df = self.query(
                f"SELECT DISTINCT article_id, CAST(product_code AS varchar) AS product_code "
                f"FROM {self.database}.{metric[channel]}_runs WHERE run_id = {literal(run['run_id'])}"
            )
            if list(df.columns) != ["article_id", "product_code"] or df.isna().any().any():
                raise GoldAError("공개 상품 목록의 형식이 잘못됐습니다.")
            frames.append(df)
        result = (
            pd.concat(frames, ignore_index=True).drop_duplicates()
            if frames
            else pd.DataFrame(columns=["article_id", "product_code"])
        )
        result["name"] = result.article_id
        if result.article_id.duplicated().any():
            raise GoldAError("업무별 상품 기준정보가 다릅니다. 실행별 상품 기준을 확인해 주세요.")
        self.cache[key] = result
        return result.copy()
