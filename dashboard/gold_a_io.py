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

    def query(self, sql):
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
                    if len(records) > self.max_rows:
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

    def run(self, channel):
        if channel not in {"trade", "funnels", "reviews"}:
            raise GoldAError("지원하지 않는 Gold A 업무입니다.")
        if channel not in self.runs:
            if self.mode == "demo" and channel == "funnels":
                if self.funnel_evidence is None:
                    raise GoldAError("퍼널 시연 근거 조회 설정이 없습니다.")
                row = self.funnel_evidence.latest()
                actual = self.query(" UNION ALL ".join(
                    f"SELECT '{name}' AS metric, count(*) AS n FROM {self.database}.{name}_runs "
                    f"WHERE run_id = {literal(row['run_id'])}" + (" AND channel = 'funnels'" if name == "refresh_holds" else "")
                    for name in ("funnel_daily", "funnel_session_product", "refresh_holds")
                ))
                if (list(actual.columns) != ["metric", "n"] or len(actual) != 3
                        or dict(zip(actual.metric, actual.n.astype(int), strict=True)) != row["tables"]):
                    raise GoldAError("시연 퍼널의 Athena 건수가 완료 manifest와 다릅니다.")
                self.runs[channel] = row
                return row
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
            df = self.query(
                f"SELECT {', '.join(columns)} FROM {self.database}.{table}_runs WHERE {where}{suffix}"
            )
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
